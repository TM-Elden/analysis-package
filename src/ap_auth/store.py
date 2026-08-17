"""AuthStore: the C11 user/session/service-token store backing real HTTP authentication.

Replaces the phase-2 `X-Ap-Actor-*` header placeholder (see `ap_auth.identity` module docstring,
now updated) with real credentials: a `users` table (scrypt password hash, roles) and a `sessions`
table used for both browser sessions (`kind="session"`) and service-account bearer tokens
(`kind="bearer"`) - same shape, same validation path, see `identity_for_token`.

Mirrors `ap_store.PackageStore`'s connection pattern deliberately (one `check_same_thread=False`
connection + an `RLock`) - see `ap_auth.db` module docstring for why this is a sibling DB rather
than tables on `ap_store`'s index.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import threading
from dataclasses import dataclass
from pathlib import Path

from ap_auth.db import connect
from ap_auth.identity import Identity, IdentityError, parse_roles
from ap_auth.models import AuthAuditEntry, SessionRecord, UserRecord
from ap_auth.passwords import hash_password, verify_password
from ap_auth.roles import Role

#: Default location, overridable via AP_AUTH_DB - see ap_api/deps.py::get_auth_store and
#: ap_auth/cli.py, both of which resolve the same default so `ap-auth adduser` and the running API
#: agree on where the user table lives without either hardcoding the other's path.
DEFAULT_AUTH_DB = Path.home() / ".fathm" / "auth.sqlite3"

#: Browser session lifetime. Short-ish and renewed by logging in again - there is no refresh-token
#: dance in v0 (design doc: "boring, stdlib-first").
SESSION_TTL = dt.timedelta(hours=12)

#: Service-account bearer tokens default to a long lifetime (CI/agents shouldn't have to re-mint
#: daily) but are not eternal - `ap-auth token --ttl-days` can override either direction.
SERVICE_TOKEN_TTL = dt.timedelta(days=365)


class AuthError(Exception):
    """Base for auth-store errors (unknown user, duplicate user, disabled user, etc.)."""


class LastAdminError(AuthError):
    """Refused: this action would leave zero enabled admin users (P5.3 last-admin guard). Raised by
    `set_roles` (removing the admin role) and `set_disabled` (disabling), before either mutation is
    applied - console lockout otherwise means SSH + `ap-auth` archaeology to recover, per the phase-5
    report's §5.3 rationale."""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(ts: dt.datetime) -> str:
    return ts.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(raw: str) -> dt.datetime:
    return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@dataclass
class AuthStore:
    db_path: Path | str = DEFAULT_AUTH_DB

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        self.conn = connect(self.db_path)
        self._lock = threading.RLock()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "AuthStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- user management --------------------------------------------------

    def create_user(
        self,
        user_id: str,
        *,
        display_name: str,
        roles: frozenset[Role],
        password: str | None = None,
        actor: Identity | None = None,
    ) -> UserRecord:
        if not user_id:
            raise AuthError("user id must be non-empty")
        if not roles:
            raise AuthError("a user must have at least one role")
        password_hash = hash_password(password) if password else None
        roles_csv = ",".join(sorted(r.value for r in roles))
        with self._lock, self.conn:
            existing = self.conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone()
            if existing is not None:
                raise AuthError(f"user {user_id!r} already exists")
            self.conn.execute(
                "INSERT INTO users (id, display_name, password_hash, roles, disabled, created_at) "
                "VALUES (?,?,?,?,0,?)",
                (user_id, display_name, password_hash, roles_csv, _iso(_utcnow())),
            )
            self._insert_auth_audit(actor, user_id, "created", f"roles: {roles_csv}")
        return self.get_user(user_id)  # type: ignore[return-value]

    def set_password(self, user_id: str, password: str, *, actor: Identity | None = None) -> None:
        with self._lock, self.conn:
            cur = self.conn.execute(
                "UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), user_id)
            )
            if cur.rowcount == 0:
                raise AuthError(f"no such user: {user_id!r}")
            self._insert_auth_audit(actor, user_id, "password_reset", None)

    def set_disabled(self, user_id: str, disabled: bool, *, actor: Identity | None = None) -> None:
        """Disabling a user also revokes every session/token they currently hold (defense in
        depth - a disabled account shouldn't stay live via an outstanding token until it expires).

        Refuses (`LastAdminError`) to disable the sole remaining enabled admin - the P5.3
        last-admin guard (see that class's docstring). Re-enabling is never guarded."""
        with self._lock, self.conn:
            if disabled:
                row = self.conn.execute("SELECT roles, disabled FROM users WHERE id=?", (user_id,)).fetchone()
                if row is None:
                    raise AuthError(f"no such user: {user_id!r}")
                if not row["disabled"] and Role.ADMIN in parse_roles(row["roles"]):
                    if self._count_enabled_admins(exclude_user_id=user_id) == 0:
                        raise LastAdminError(
                            f"refusing to disable {user_id!r}: they are the last enabled admin user"
                        )
            cur = self.conn.execute("UPDATE users SET disabled=? WHERE id=?", (int(disabled), user_id))
            if cur.rowcount == 0:
                raise AuthError(f"no such user: {user_id!r}")
            if disabled:
                self.conn.execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (user_id,))
            self._insert_auth_audit(actor, user_id, "disabled" if disabled else "enabled", None)

    def set_roles(self, user_id: str, roles: frozenset[Role], *, actor: Identity | None = None) -> UserRecord:
        """Add/edit a user's role set (the one store method the P5.3 plan found genuinely missing).

        Refuses (`LastAdminError`) an edit that would leave zero enabled admin users - i.e.
        removing `admin` from the last enabled user who holds it. A disabled user never counts
        towards "enabled admin" either way, so editing a disabled admin's roles is never guarded."""
        if not roles:
            raise AuthError("a user must have at least one role")
        with self._lock, self.conn:
            row = self.conn.execute("SELECT roles, disabled FROM users WHERE id=?", (user_id,)).fetchone()
            if row is None:
                raise AuthError(f"no such user: {user_id!r}")
            was_admin = Role.ADMIN in parse_roles(row["roles"])
            still_admin = Role.ADMIN in roles
            if not row["disabled"] and was_admin and not still_admin:
                if self._count_enabled_admins(exclude_user_id=user_id) == 0:
                    raise LastAdminError(
                        f"refusing to remove admin from {user_id!r}: they are the last enabled admin user"
                    )
            roles_csv = ",".join(sorted(r.value for r in roles))
            self.conn.execute("UPDATE users SET roles=? WHERE id=?", (roles_csv, user_id))
            self._insert_auth_audit(actor, user_id, "role_change", f"{row['roles']} -> {roles_csv}")
        return self.get_user(user_id)  # type: ignore[return-value]

    def _count_enabled_admins(self, *, exclude_user_id: str | None = None) -> int:
        """Count of enabled users holding the admin role, excluding `exclude_user_id` (the user
        under edit - its own current row must not count towards its own guard check)."""
        rows = self.conn.execute("SELECT id, roles FROM users WHERE disabled=0").fetchall()
        return sum(
            1
            for r in rows
            if r["id"] != exclude_user_id and Role.ADMIN in parse_roles(r["roles"])
        )

    def get_user(self, user_id: str) -> UserRecord | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return self._row_to_user(row) if row else None

    def list_users(self) -> list[UserRecord]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()
        return [self._row_to_user(r) for r in rows]

    # -- login / tokens -----------------------------------------------------

    def verify_login(self, user_id: str, password: str) -> Identity | None:
        """Returns the caller's Identity on a correct password against an enabled user, else None.
        Never raises on bad credentials (that would leak which half was wrong via exception type)."""
        with self._lock:
            row = self.conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None or row["disabled"] or not row["password_hash"]:
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        try:
            return Identity(id=row["id"], roles=parse_roles(row["roles"]))
        except IdentityError:
            return None

    def create_session(self, user_id: str, *, ttl: dt.timedelta = SESSION_TTL) -> str:
        return self._issue_token(user_id, kind="session", ttl=ttl)

    def create_service_token(
        self, user_id: str, *, ttl: dt.timedelta = SERVICE_TOKEN_TTL, actor: Identity | None = None
    ) -> str:
        token = self._issue_token(user_id, kind="bearer", ttl=ttl)
        with self._lock, self.conn:
            self._insert_auth_audit(actor, user_id, "token_issue", None)
        return token

    def _issue_token(self, user_id: str, *, kind: str, ttl: dt.timedelta) -> str:
        with self._lock:
            user = self.conn.execute("SELECT 1 FROM users WHERE id=? AND disabled=0", (user_id,)).fetchone()
        if user is None:
            raise AuthError(f"no such enabled user: {user_id!r}")
        raw_token = secrets.token_urlsafe(32)
        now = _utcnow()
        expires_at = _iso(now + ttl) if ttl else None
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO sessions (token_hash, user_id, kind, created_at, expires_at, revoked) "
                "VALUES (?,?,?,?,?,0)",
                (_hash_token(raw_token), user_id, kind, _iso(now), expires_at),
            )
        return raw_token

    def revoke_token(self, raw_token: str) -> None:
        with self._lock, self.conn:
            self.conn.execute("UPDATE sessions SET revoked=1 WHERE token_hash=?", (_hash_token(raw_token),))

    def revoke_session_by_hash(self, token_hash: str, *, actor: Identity | None = None) -> None:
        """Admin-facing revoke: the console never sees a raw token (only ever returned once, at
        issuance - see `_issue_token`), so its per-user sessions/tokens view revokes by the stored
        `token_hash` instead. `token_hash` is a sha256 digest, not a secret, so accepting it here is
        not an oracle for token guessing."""
        with self._lock, self.conn:
            row = self.conn.execute("SELECT user_id FROM sessions WHERE token_hash=?", (token_hash,)).fetchone()
            if row is None:
                raise AuthError(f"no such session/token: {token_hash!r}")
            self.conn.execute("UPDATE sessions SET revoked=1 WHERE token_hash=?", (token_hash,))
            self._insert_auth_audit(actor, row["user_id"], "token_revoke", None)

    def list_sessions(self, user_id: str) -> list[SessionRecord]:
        """Every session/service-token row for `user_id`, newest first - the P5.3 sessions/tokens
        view. `kind` distinguishes browser sessions from service-account bearer tokens (display
        only, both validate identically - see `identity_for_token`)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM sessions WHERE user_id=? ORDER BY created_at DESC", (user_id,)
            ).fetchall()
        return [
            SessionRecord(
                token_hash=r["token_hash"],
                user_id=r["user_id"],
                kind=r["kind"],
                created_at=r["created_at"],
                expires_at=r["expires_at"],
                revoked=bool(r["revoked"]),
            )
            for r in rows
        ]

    def identity_for_token(self, raw_token: str) -> Identity | None:
        """Resolves either a browser session token or a service bearer token to an Identity.
        Returns None on missing/revoked/expired token or a disabled/deleted user - callers map that
        uniformly to 401, never distinguishing which (no oracle for token guessing)."""
        with self._lock:
            row = self.conn.execute(
                "SELECT s.*, u.roles as user_roles, u.disabled as user_disabled "
                "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=?",
                (_hash_token(raw_token),),
            ).fetchone()
        if row is None or row["revoked"] or row["user_disabled"]:
            return None
        if row["expires_at"] and _utcnow() > _parse_iso(row["expires_at"]):
            return None
        try:
            return Identity(id=row["user_id"], roles=parse_roles(row["user_roles"]))
        except IdentityError:
            return None

    # -- audit ------------------------------------------------------------

    def audit_trail(self, user_id: str | None = None) -> list[AuthAuditEntry]:
        """Full `auth_audit` history, newest first - either every row (Admin tab's global view) or
        scoped to one `target_user_id` (a user's own detail panel)."""
        with self._lock:
            if user_id is None:
                rows = self.conn.execute("SELECT * FROM auth_audit ORDER BY id DESC").fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM auth_audit WHERE target_user_id=? ORDER BY id DESC", (user_id,)
                ).fetchall()
        return [
            AuthAuditEntry(
                id=r["id"],
                actor_id=r["actor_id"],
                actor_roles=r["actor_roles"],
                target_user_id=r["target_user_id"],
                action=r["action"],
                detail=r["detail"],
                ts=r["ts"],
            )
            for r in rows
        ]

    def _insert_auth_audit(
        self, actor: Identity | None, target_user_id: str, action: str, detail: str | None
    ) -> None:
        """Caller must already hold `self._lock`/`self.conn` transaction - mirrors
        `ap_store.PackageStore._insert_audit`'s same-transaction pattern so a mutation and its audit
        row are never observably split. `actor` is `None` only for the `ap-auth` CLI bootstrap path
        (no HTTP identity yet exists) - see `ap_auth.db` module docstring."""
        self.conn.execute(
            "INSERT INTO auth_audit (actor_id, actor_roles, target_user_id, action, detail, ts) "
            "VALUES (?,?,?,?,?,?)",
            (
                actor.id if actor else None,
                actor.roles_csv() if actor else None,
                target_user_id,
                action,
                detail,
                _iso(_utcnow()),
            ),
        )

    # -- internals ------------------------------------------------------

    def _row_to_user(self, row) -> UserRecord:
        return UserRecord(
            id=row["id"],
            display_name=row["display_name"],
            roles=row["roles"],
            disabled=bool(row["disabled"]),
            created_at=row["created_at"],
            has_password=row["password_hash"] is not None,
        )
