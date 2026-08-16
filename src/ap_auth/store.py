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
from ap_auth.models import UserRecord
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
        return self.get_user(user_id)  # type: ignore[return-value]

    def set_password(self, user_id: str, password: str) -> None:
        with self._lock, self.conn:
            cur = self.conn.execute(
                "UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), user_id)
            )
            if cur.rowcount == 0:
                raise AuthError(f"no such user: {user_id!r}")

    def set_disabled(self, user_id: str, disabled: bool) -> None:
        """Disabling a user also revokes every session/token they currently hold (defense in
        depth - a disabled account shouldn't stay live via an outstanding token until it expires)."""
        with self._lock, self.conn:
            cur = self.conn.execute("UPDATE users SET disabled=? WHERE id=?", (int(disabled), user_id))
            if cur.rowcount == 0:
                raise AuthError(f"no such user: {user_id!r}")
            if disabled:
                self.conn.execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (user_id,))

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

    def create_service_token(self, user_id: str, *, ttl: dt.timedelta = SERVICE_TOKEN_TTL) -> str:
        return self._issue_token(user_id, kind="bearer", ttl=ttl)

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
