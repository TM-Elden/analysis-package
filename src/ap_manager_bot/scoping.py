"""Identity -> retrieval-filter scoping (C4's "resolve caller identity to filters before search,
re-verify after search" double-check pattern - report section 5.3).

Corpus scoping today has two independent dimensions:

1. **Review status**: only `approved` packages are ever indexed at all (`ap_index.reindex`'s
   "approved -> index; anything else -> ensure removed" rule) - so status scoping is structural,
   not something this module re-derives.
2. **Confidentiality-by-role**: `confidentiality` (a free-form manifest string, e.g. `"internal"` /
   `"internal_restricted"`) maps to the set of roles allowed to retrieve it. No `team_id` exists yet
   (report: "team scope once teams exist") so this is deliberately coarse - two tiers, not a matrix -
   and is the seam a future per-team scope slots into without changing callers of this module.
"""

from __future__ import annotations

from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_index.models import ChunkRecord

#: Confidentiality values visible to any authenticated caller - the default tier. A package with no
#: `confidentiality` set at all does not reach this module (the manifest schema requires the field;
#: see standard/ap-0.2/schemas/manifest.schema.json), so there is no implicit-default case to handle.
BASE_VISIBLE_CONFIDENTIALITY = ("internal",)

#: Confidentiality values that additionally require one of `_ELEVATED_ROLES` (or admin, which
#: `Identity.has_role` always treats as a bypass). `internal_restricted` is the value the example
#: package and the agent-tools template both ship with - the conservative "most packages need this"
#: default noted in CLAUDE.md's C14 section.
RESTRICTED_CONFIDENTIALITY = ("internal_restricted",)

_ELEVATED_ROLES = (Role.ANALYST, Role.REVIEWER, Role.STANDARD_APPROVER)


def confidentiality_filter_for(identity: Identity) -> tuple[str, ...]:
    """The `confidentiality` values `identity` may retrieve - pass straight to
    `ap_index.models.SearchFilters.confidentiality_in`. Computed once per request, before any
    search call (the "pre" half of the double-check)."""
    tiers = set(BASE_VISIBLE_CONFIDENTIALITY)
    if any(identity.has_role(r) for r in _ELEVATED_ROLES):
        tiers |= set(RESTRICTED_CONFIDENTIALITY)
    return tuple(sorted(tiers))


def chunk_in_scope(identity: Identity, chunk: ChunkRecord) -> bool:
    """Re-verify one already-retrieved chunk against `identity`'s scope - the "post" half of the
    double-check. Called on every chunk before it enters the LLM prompt or a citation, independent
    of whatever filter the search call itself already applied - defense in depth against a filter
    that was built wrong, omitted, or bypassed (e.g. a direct `get_chunk` lookup)."""
    return chunk.confidentiality in confidentiality_filter_for(identity)
