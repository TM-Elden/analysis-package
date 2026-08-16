"""`GET /standard/versions` (design report §5.5): supported `standard_version`s plus per-profile
registry versions and their changelogs - the pull surface a future notify/agent-docs task points
agents at. Read-only, no proposal/registry mutation here; `ap_proposals.workflow.ProposalWorkflow`
is what writes the registry (see that module + `ap_proposals.apply`).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ap_api.deps import get_proposal_store, identity_from_request
from ap_api.schemas import ProfileVersionsOut, StandardVersionsOut
from ap_auth.identity import Identity
from ap_gate.versions import supported_versions
from ap_proposals.store import ProposalStore
from ap_registry.profile_registry import ProfileRegistry

router = APIRouter()


@router.get("/standard/versions", response_model=StandardVersionsOut)
def get_standard_versions(
    _actor: Annotated[Identity, Depends(identity_from_request)],
    # ProposalStore is depended on only for `.root` - the same store_root the registry lives
    # under (see ProposalWorkflow's default registry construction) - not for any proposal read.
    proposal_store: Annotated[ProposalStore, Depends(get_proposal_store)],
) -> StandardVersionsOut:
    registry = ProfileRegistry(proposal_store.root)
    profiles = [
        ProfileVersionsOut(
            name=name,
            current_version=registry.current_version(name),
            changelog=registry.changelog(name),
        )
        for name in registry.names()
    ]
    return StandardVersionsOut(standard_versions=supported_versions(), profiles=profiles)
