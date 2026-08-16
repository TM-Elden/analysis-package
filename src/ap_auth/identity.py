"""Identity model and caller identification (C11 scaffold).

Phase 2 has no login/session system - there is no UI to authenticate against yet (see
docs/DESIGN-FATHM-SYSTEM.md C11 and section 20a, which explicitly defers web authentication to
phase 3). What phase 2 DOES fix is the *shape* identity takes everywhere in the codebase, so phase
3's web authentication has something concrete to plug into rather than retrofitting one under a UI
deadline:

- Library callers (agent scripts, tests) construct an `Identity` directly.
- CLI / agent callers identify themselves via the `AP_ACTOR_ID` and `AP_ACTOR_ROLES`
  (comma-separated) environment variables - see `identity_from_env()`.
- HTTP callers (`ap_api`) identify themselves via the `X-Ap-Actor-Id` / `X-Ap-Actor-Roles` headers
  - see `ap_api.deps.identity_from_request()`. This is a **placeholder, not authentication**: any
    caller can claim any identity by setting the header, there is no signature or session behind
    it. Phase 3 replaces the header source with an identity derived from a real authenticated
    session/token; every call site downstream of identity extraction keeps working unchanged
    across that swap because they only ever see this same `Identity` dataclass.

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
