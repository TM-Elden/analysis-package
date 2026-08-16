"""C6/C7 proposal API (design doc section 15): `GET /proposals`, `POST /proposals`,
`POST /proposals/{id}/decision`, `POST /proposals/{id}/dry-run`, `GET /proposals/{id}/spec`.

Same JSON-layer discipline as `ap_api/app.py`'s package routes: every route requires *some*
authenticated identity (`identity_from_request`), no anonymous access. Reads are unrestricted by
role, same reasoning as `GET /packages*` - no team/company scoping exists yet (single-tenant, see
CLAUDE.md). `POST /proposals` (create) is deliberately **not** role-gated at the route level - the
brief is explicit that creating requires only "any authenticated internal identity", not a role
restriction (`ProposalWorkflow.create` mirrors this) - mirroring how `POST /packages/{id}/review`
lets `ReviewWorkflow` itself own the role matrix rather than double-gating at the route. Decision
role enforcement (`standard_approver`) similarly lives in `ProposalWorkflow.decide`, which raises
`ProposalPolicyError` (mapped to 403 here) rather than a route-level `require_any_role` dependency.
`POST /proposals/{id}/dry-run` is deliberately not role-gated either - running a dry-run changes
nothing decision-relevant by itself (it only populates `dry_run_json`, which `decide` still
independently policy-checks) and any authenticated caller may want to preview one ahead of a real
decision. `ap_console` will read `ProposalStore` directly later, same module-boundary pattern as
the review queue - no console UI is built here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from ap_api.deps import get_proposal_store, get_proposal_workflow, get_store, identity_from_request
from ap_api.schemas import (
    ProposalCreateRequest,
    ProposalDecisionRequest,
    ProposalListResponse,
    ProposalOut,
    proposal_record_to_out,
)
from ap_auth.identity import Identity
from ap_proposals.apply import ProposalApplyError
from ap_proposals.kinds import ProposalValidationError
from ap_proposals.store import ListFilter, ProposalStore, ProposalStoreError
from ap_proposals.workflow import ProposalPolicyError, ProposalWorkflow
from ap_store.store import PackageStore

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
    except ProposalApplyError as exc:
        # The apply step (registry write) itself failed - the proposal is still pending_hitl
        # (see ProposalWorkflow.decide's docstring), not a client error, so this is a 502
        # (upstream/dependency failure), distinct from the 403/400/404/409 cases above.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ProposalStoreError as exc:
        status_code = 404 if "no such proposal" in str(exc) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return proposal_record_to_out(record)


@router.post("/proposals/{proposal_id}/dry-run", response_model=ProposalOut)
def dry_run_proposal(
    proposal_id: str,
    _actor: Annotated[Identity, Depends(identity_from_request)],
    workflow: Annotated[ProposalWorkflow, Depends(get_proposal_workflow)],
    package_store: Annotated[PackageStore, Depends(get_store)],
) -> ProposalOut:
    """Run `ap_planner_bot.dry_run.dry_run` for a declarative-kind proposal and persist the
    result - satisfies `decide`'s "no declarative approval without a dry-run on record"
    requirement (§5.6). Any authenticated caller may run this; see module docstring for why it
    isn't role-gated."""
    try:
        record = workflow.record_dry_run(proposal_id, package_store)
    except ProposalPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProposalStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return proposal_record_to_out(record)


@router.get("/proposals/{proposal_id}/spec")
def get_proposal_spec(
    proposal_id: str,
    _actor: Annotated[Identity, Depends(identity_from_request)],
    store: Annotated[ProposalStore, Depends(get_proposal_store)],
) -> PlainTextResponse:
    """Retrieve the markdown spec artifact a `standard_change`/`check_add` approval exported
    (`ap_proposals.apply.export_spec`) - the concrete, retrievable artifact §5.5 requires for
    code-kind proposals (a human takes this into a normal PR; nothing here applies it)."""
    record = store.get(proposal_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no such proposal: {proposal_id}")
    if not record.spec_artifact_path:
        raise HTTPException(
            status_code=404,
            detail=f"proposal {proposal_id!r} has no spec artifact - only an approved standard_change/"
            "check_add proposal has one (declarative kinds apply to the registry instead)",
        )
    path = store.root / record.spec_artifact_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"spec artifact for {proposal_id!r} is recorded but missing on disk")
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")
