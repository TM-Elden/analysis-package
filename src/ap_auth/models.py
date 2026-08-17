"""Read-model dataclass for AuthStore.get_user / list_users. See ap_auth.db for the schema."""

from __future__ import annotations

from dataclasses import dataclass

from ap_auth.identity import Identity
from ap_auth.identity import parse_roles as _parse_roles


@dataclass(frozen=True)
class UserRecord:
    id: str
    display_name: str
    roles: str  # CSV, same encoding as Identity.roles_csv()
    disabled: bool
    created_at: str
    has_password: bool

    def to_identity(self) -> Identity:
        return Identity(id=self.id, roles=_parse_roles(self.roles))


@dataclass(frozen=True)
class SessionRecord:
    """A `sessions` row for admin/audit display only - never the raw token (see `ap_auth.db`
    module docstring). `token_hash` is a sha256 digest, not a secret derivable back to the raw
    token, so it is safe to use as the row identifier the console's revoke button posts back."""

    token_hash: str
    user_id: str
    kind: str  # "session" (browser login) or "bearer" (service-account token)
    created_at: str
    expires_at: str | None
    revoked: bool


@dataclass(frozen=True)
class AuthAuditEntry:
    id: int
    actor_id: str | None
    actor_roles: str | None
    target_user_id: str
    action: str
    detail: str | None
    ts: str
