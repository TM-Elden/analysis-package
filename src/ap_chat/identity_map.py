"""Explicit chat-platform-user -> fathm-identity allowlist (task requirement 3; C11 "bots inherit
the caller's authz" honestly).

This is deliberately **not** auto-provisioning: a platform user id that isn't in the allowlist file
gets a polite refusal, never a fathm identity minted on the fly. An operator adds a row here only
after provisioning the person a real fathm service account - historically via
`ap-auth adduser --no-password --roles team_reader <fathm_user_id>` then `ap-auth token
<fathm_user_id>` (see `docs/telegram-bot-setup.md`), and as of P5.4 also via the console's "Team bot
access" admin screen (`ap_console/admin_routes.py`), which composes `add_entry`/`remove_entry`
below with `AuthStore.create_user`/`create_service_token`/`set_disabled`. Either way the bearer
token in this file *is* that person's scoped fathm identity; `POST /chat/manager` resolves it
through the exact same `identity_from_request` path any other bearer-token caller goes through
(`ap_api/deps.py`), so scoping/citation rules are identical to any other C11 caller.

File format is a flat JSON object, platform-neutral key name (`platform_user_id`) so the same
loader/shape serves a future Slack allowlist file without changing this module:

```json
{
  "123456789": {"fathm_user_id": "planner.alice", "token": "<service-account bearer token>"},
  "987654321": {"fathm_user_id": "planner.bob", "token": "<service-account bearer token>"}
}
```
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: Default allowlist location, overridable via AP_CHAT_ALLOWLIST_PATH - the same default
#: `docs/telegram-bot-setup.md` and `ap_chat/telegram/__main__.py` document, now also the console
#: provisioning flow's default (`ap_console/admin_routes.py`) so both agree without either
#: hardcoding the other's path.
DEFAULT_ALLOWLIST_PATH = Path.home() / ".fathm" / "chat_telegram_allowlist.json"


class AllowlistError(Exception):
    """Raised on a malformed allowlist file - fails closed at startup rather than silently running
    with an empty or partially-loaded map."""


@dataclass(frozen=True)
class MappedIdentity:
    fathm_user_id: str
    token: str


def _parse_raw(text: str, path: Path) -> dict:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AllowlistError(f"allowlist file {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise AllowlistError(f"allowlist file {path} must be a JSON object keyed by platform user id")
    return raw


def _load_raw_or_empty(path: Path) -> dict:
    """Same parse as `_parse_raw`, but a missing file reads as "nobody provisioned yet" (`{}`)
    rather than a startup failure - the right default for the console's read/write helpers below,
    which may run before any entry has ever been written. `IdentityAllowlist.load()` (the chat
    bot's own startup path) deliberately keeps the stricter "must already exist" contract."""
    if not path.exists():
        return {}
    return _parse_raw(path.read_text(), path)


def _row_to_identity(platform_user_id: str, row: object, path: Path) -> MappedIdentity:
    if not isinstance(row, dict) or "fathm_user_id" not in row or "token" not in row:
        raise AllowlistError(
            f"allowlist entry {platform_user_id!r} in {path} must be an object with 'fathm_user_id' and 'token'"
        )
    return MappedIdentity(fathm_user_id=row["fathm_user_id"], token=row["token"])


def read_entries(path: Path) -> dict[str, MappedIdentity]:
    """Every provisioned entry, keyed by platform user id - `{}` if the file doesn't exist yet.
    Used by the console's access-list table (`ap_console/admin_routes.py`), which must render
    before any planner has ever been provisioned."""
    raw = _load_raw_or_empty(path)
    return {str(pid): _row_to_identity(str(pid), row, path) for pid, row in raw.items()}


def _write_atomic(path: Path, data: dict) -> None:
    """write-temp-then-`os.replace` in the same directory as `path` (so the replace is on the same
    filesystem) - the established pattern for shared-state files in this codebase, see
    `ap_registry.profile_registry`'s pointer writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".allowlist-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def add_entry(path: Path, platform_user_id: str, *, fathm_user_id: str, token: str) -> None:
    """Provision (or overwrite) one allowlist row - the console provisioning flow's third step,
    after `AuthStore.create_user`/`create_service_token`. The raw token is written here and nowhere
    else (never logged, never echoed back to the caller)."""
    data = _load_raw_or_empty(path)
    data[str(platform_user_id)] = {"fathm_user_id": fathm_user_id, "token": token}
    _write_atomic(path, data)


def remove_entry(path: Path, platform_user_id: str) -> bool:
    """Revoke's second step (after `AuthStore.set_disabled`). Returns whether a row was actually
    removed - a no-op write is skipped for an already-absent id."""
    data = _load_raw_or_empty(path)
    if data.pop(str(platform_user_id), None) is None:
        return False
    _write_atomic(path, data)
    return True


class IdentityAllowlist:
    """Loaded once at startup; re-`load()` to pick up edits without a restart (an operator adding
    a row shouldn't require bouncing the systemd unit) - `ap_chat.runner.BotRunner` now calls this
    itself on a resolve-miss (P5.4 "reload-on-miss")."""

    def __init__(self, path: Path):
        self.path = path
        self._entries: dict[str, MappedIdentity] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            raise AllowlistError(f"allowlist file not found: {self.path}")
        self._entries = read_entries(self.path)

    def resolve(self, platform_user_id: str) -> MappedIdentity | None:
        return self._entries.get(platform_user_id)
