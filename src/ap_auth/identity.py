"""Identity model and caller identification (C11).

Phase 2 built the *shape* identity takes everywhere in the codebase, precisely so phase 3's real
web authentication had something concrete to plug into instead of retrofitting one under a UI
deadline. Phase 3 (`ap_auth.store.AuthStore` + `ap_api/deps.py::identity_from_request`) is that
plug-in: real scrypt-hashed passwords, server-side sessions, and service-account bearer tokens
replace the old `X-Ap-Actor-*` header placeholder - see CLAUDE.md's "C11 auth model" section for the
concrete mechanism. Every call site downstream of identity extraction is unchanged across that swap
because they only ever see this same `Identity` dataclass:

- Library callers (agent scripts, tests) construct an `Identity` directly.
- CLI / agent callers identify themselves via the `AP_ACTOR_ID` and `AP_ACTOR_ROLES`
  (comma-separated) environment variables - see `identity_from_env()`. This stays for same-machine
  tooling that never crosses a trust boundary (it never claims to be authentication).
- HTTP callers (`ap_api`) authenticate for real: a browser session cookie (`POST /login`) or an
  `Authorization: Bearer <token>` service-account token, both resolved by
  `ap_api.deps.identity_from_request` via `ap_auth.store.AuthStore`.

Every state-changing action in `ap_store` / `ap_review` takes an `Identity` and records its `id` +
`roles` in the audit trail - never a bare string.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ap_auth.roles import Role


class IdentityError(Exception):
    """Raised when a caller does not identify itself (missing/malformed actor)."""


@dataclass(frozen=True)
class Identity:
    id: str
    roles: frozenset[Role]

    def __post_init__(self) -> None:
        if not self.id:
            raise IdentityError("Identity.id must be non-empty")
        if not self.roles:
            raise IdentityError("Identity.roles must be non-empty")

    def has_role(self, role: Role) -> bool:
        """True if the identity holds `role` directly, or holds admin (admin bypasses every check)."""
        return role in self.roles or Role.ADMIN in self.roles

    def roles_csv(self) -> str:
        return ",".join(sorted(r.value for r in self.roles))


def parse_roles(raw: str) -> frozenset[Role]:
    names = [r.strip() for r in raw.split(",") if r.strip()]
    if not names:
        raise IdentityError("no roles given")
    try:
        return frozenset(Role(n) for n in names)
    except ValueError as exc:
        known = ", ".join(r.value for r in Role)
        raise IdentityError(f"unknown role in {raw!r} (known roles: {known}): {exc}") from exc


def identity_from_env() -> Identity:
    """CLI/agent identification: AP_ACTOR_ID + AP_ACTOR_ROLES env vars.

    e.g. AP_ACTOR_ID=planner.tom AP_ACTOR_ROLES=analyst ap-store publish ./my-package
    """
    actor_id = os.environ.get("AP_ACTOR_ID")
    roles_raw = os.environ.get("AP_ACTOR_ROLES")
    if not actor_id or not roles_raw:
        raise IdentityError(
            "AP_ACTOR_ID and AP_ACTOR_ROLES must both be set to identify the calling CLI/agent "
            "(e.g. AP_ACTOR_ID=planner.tom AP_ACTOR_ROLES=analyst)"
        )
    return Identity(id=actor_id, roles=parse_roles(roles_raw))
