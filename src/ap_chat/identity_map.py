"""Explicit chat-platform-user -> fathm-identity allowlist (task requirement 3; C11 "bots inherit
the caller's authz" honestly).

This is deliberately **not** auto-provisioning: a platform user id that isn't in the allowlist file
gets a polite refusal, never a fathm identity minted on the fly. An operator adds a row here only
after provisioning the person a real fathm service account (`ap-auth adduser --no-password
--roles team_reader <fathm_user_id>` then `ap-auth token <fathm_user_id>` - see
`docs/telegram-bot-setup.md`) - the bearer token in this file *is* that person's scoped fathm
identity; `POST /chat/manager` resolves it through the exact same `identity_from_request` path any
other bearer-token caller goes through (`ap_api/deps.py`), so scoping/citation rules are identical
to any other C11 caller. Per-team-member bot *provisioning* (auto-creating the fathm account itself)
is explicitly out of scope here - tracked separately as `fathm-phase3-team-bot-provisioning`.

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
from dataclasses import dataclass
from pathlib import Path


class AllowlistError(Exception):
    """Raised on a malformed allowlist file - fails closed at startup rather than silently running
    with an empty or partially-loaded map."""


@dataclass(frozen=True)
class MappedIdentity:
    fathm_user_id: str
    token: str


class IdentityAllowlist:
    """Loaded once at startup; re-`load()` to pick up edits without a restart (an operator adding
    a row shouldn't require bouncing the systemd unit)."""

    def __init__(self, path: Path):
        self.path = path
        self._entries: dict[str, MappedIdentity] = {}
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
        except FileNotFoundError as exc:
            raise AllowlistError(f"allowlist file not found: {self.path}") from exc
        except json.JSONDecodeError as exc:
            raise AllowlistError(f"allowlist file {self.path} is not valid JSON: {exc}") from exc

        if not isinstance(raw, dict):
            raise AllowlistError(f"allowlist file {self.path} must be a JSON object keyed by platform user id")

        entries: dict[str, MappedIdentity] = {}
        for platform_user_id, row in raw.items():
            if not isinstance(row, dict) or "fathm_user_id" not in row or "token" not in row:
                raise AllowlistError(
                    f"allowlist entry {platform_user_id!r} must be an object with 'fathm_user_id' and 'token'"
                )
            entries[str(platform_user_id)] = MappedIdentity(fathm_user_id=row["fathm_user_id"], token=row["token"])
        self._entries = entries

    def resolve(self, platform_user_id: str) -> MappedIdentity | None:
        return self._entries.get(platform_user_id)
