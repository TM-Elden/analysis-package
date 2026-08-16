"""C6/C7 proposal API (design doc section 15): `GET /proposals`, `POST /proposals`,
`POST /proposals/{id}/decision`.

Same JSON-layer discipline as `ap_api/app.py`'s package routes: every route requires *some*
authenticated identity (`identity_from_request`), no anonymous access. Reads are unrestricted by
role, same reasoning as `GET /packages*` - no team/company scoping exists yet (single-tenant, see
CLAUDE.md). `POST /proposals` (create) is deliberately **not** role-gated at the route level - the
brief is explicit that creating requires only "any authenticated internal identity", not a role
restriction (`ProposalWorkflow.create` mirrors this) - mirroring how `POST /packages/{id}/review`
lets `ReviewWorkflow` itself own the role matrix rather than double-gating at the route. Decision
role enforcement (`standard_approver`) similarly lives in `ProposalWorkflow.decide`, which raises
`ProposalPolicyError` (mapped to 403 here) rather than a route-level `require_any_role` dependency.
`ap_console` will read `ProposalStore` directly later, same module-boundary pattern as the review
queue - no console UI is built here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ap_api.deps import get_proposal_store, get_proposal_workflow, identity_from_request
from ap_api.schemas import (
    ProposalCreateRequest,
    ProposalDecisionRequest,
    ProposalListResponse,
    ProposalOut,
    proposal_record_to_out,
)
from ap_auth.identity import Identity
from ap_proposals.kinds import ProposalValidationError
from ap_proposals.store import ListFilter, ProposalStore, ProposalStoreError
from ap_proposals.workflow import ProposalPolicyError, ProposalWorkflow

router = APIRouter()


@router.get("/proposals", response_model=ProposalListResponse)
def list_proposals(
    store: Annotated[ProposalStore, Depends(get_proposal_store)],
    _actor: Annotated[Identity, Depends(identity_from_request)],
    status: str | None = None,
    kind: str | None = None,
    created_by: str | None = Query(default=None, description="Matches created_by_id"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> ProposalListResponse:
    result = store.list(ListFilter(status=status, kind=kind, created_by=created_by, page=page, page_size=page_size))
    return ProposalListResponse(
        items=[proposal_record_to_out(r) for r in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("/proposals", response_model=ProposalOut, status_code=201)
def create_proposal(
    body: ProposalCreateRequest,
    actor: Annotated[Identity, Depends(identity_from_request)],
    workflow: Annotated[ProposalWorkflow, Depends(get_proposal_workflow)],
) -> ProposalOut:
    try:
        record = workflow.create(
            kind=body.kind,
            summary=body.summary,
            rationale=body.rationale,
            diff=body.diff,
            evidence=body.evidence,
            actor=actor,
        )
    except ProposalValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProposalStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return proposal_record_to_out(record)


@router.post("/proposals/{proposal_id}/decision", response_model=ProposalOut)
def decide_proposal(
    proposal_id: str,
    body: ProposalDecisionRequest,
    actor: Annotated[Identity, Depends(identity_from_request)],
    workflow: Annotated[ProposalWorkflow, Depends(get_proposal_workflow)],
) -> ProposalOut:
    try:
        record = workflow.decide(
            proposal_id,
            to_status=body.to_status,
            actor=actor,
            reason=body.reason,
            edited_diff=body.edited_diff,
        )
    except ProposalPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ProposalValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProposalStoreError as exc:
        status_code = 404 if "no such proposal" in str(exc) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return proposal_record_to_out(record)
