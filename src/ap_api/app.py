"""FastAPI interface layer (design doc section 15) - the future phase-3 manager console's backend.

Endpoints implemented (phase-2 minimum per docs/DESIGN-FATHM-SYSTEM.md section 15 + 20a, "endpoint
shapes ... designed for a UI consumer, not just curl"):

    POST /packages/validate        - run the gate against a package directory without publishing
    POST /packages                 - publish (C3)
    POST /packages/{id}/review     - review transition (C10)
    GET  /packages/{id}            - package detail (?version= for a specific version, else latest)
    GET  /packages                 - filtered, paginated list/search (C3)
    GET  /packages/{id}/audit      - audit trail for a version (bonus beyond the section-15 minimum
                                      table; C10's acceptance bar explicitly requires "who
                                      transitioned status when" to be visible, so this is the
                                      natural read side of that requirement)

Local-first scope note: this phase-2 slice runs on the same machine/filesystem as its callers (Pi,
CI runner, agent harness) - `package_dir` in /packages/validate and /packages is a path the *server*
process can read, not an upload. No hosting/deployment model has been decided (design doc section 20,
"Hosted SaaS vs on-prem/Pi-first ... escalated rather than silently resolved"); this keeps phase 2
honest about running locally without foreclosing a later hosted deployment - a remote deployment
would swap `package_dir` for an upload step ahead of these endpoints, not change any endpoint shape
here.

AuthN/AuthZ: see `ap_auth.store.AuthStore` and `ap_api.deps` - callers authenticate with a real
session cookie (`POST /login`, `ap_api.auth_routes`) or a service-account `Authorization: Bearer`
token; every route below depends on `identity_from_request` and only ever sees the resulting
`Identity` (unchanged from phase 2's shape). Every route requires *some* authenticated identity -
there is no anonymous access, including to reads - matching C11's "every API call tenant-scoped".
Write routes additionally require a specific role via `require_any_role` (see each route below);
`ReviewWorkflow` enforces the rest of the matrix itself (analyst-only submit, reviewer-only
approve/reject, distinct-reviewer policy - see `ap_review.workflow`). Read routes (`GET /packages*`)
deliberately do not further restrict by role: with no team/company scoping implemented yet
(single-tenant, see CLAUDE.md), any authenticated identity may read - team-scoped reads are a
`ap_index`-era scoping concern (see the phase-3 report's C4 section), not this layer's job today.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query

from ap_api.auth_routes import router as auth_router
from ap_api.deps import get_store, get_workflow, identity_from_request, require_any_role
from ap_api.schemas import (
    AuditEntryOut,
    ListResponse,
    PackageOut,
    PublishRequest,
    ReviewRequest,
    ValidateRequest,
    package_record_to_out,
)
from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_console import include_console
from ap_gate.checks.context import CheckContext
from ap_gate.checks.registry import run_all
from ap_gate.load_manifest import ManifestLoadError, load_manifest
from ap_gate.report.model import build_report
from ap_review.workflow import ReviewPolicyError, ReviewWorkflow
from ap_store.store import ImmutabilityError, ListFilter, PackageStore, StoreError

app = FastAPI(
    title="ap-api",
    description="fathm phase-2 interface layer - package store (C3) + package review (C10) backend",
    version="0.1.0",
)
app.include_router(auth_router)
include_console(app)  # ap_console: the server-rendered HTML console, mounted under /console - see
# CLAUDE.md's "Phase 3 manager console" section for the ap_console/ap_api module boundary.


def _run_gate(package_path: Path) -> dict:
    try:
        manifest = load_manifest(package_path)
    except ManifestLoadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ctx = CheckContext(package_path=package_path, manifest=manifest)
    outcomes = run_all(ctx)
    return build_report(
        package_id=str(manifest.get("package_id", "(unknown)")),
        title=str(manifest.get("title", "")),
        as_of=str(manifest.get("as_of", "")),
        qa_status=str((manifest.get("qa") or {}).get("status", "")),
        profile=str(manifest.get("profile", "")),
        outcomes=outcomes,
    )


@app.post("/packages/validate")
def validate_package(
    body: ValidateRequest,
    _actor: Annotated[Identity, Depends(identity_from_request)],
) -> dict:
    package_path = Path(body.package_dir)
    if not package_path.is_dir():
        raise HTTPException(status_code=400, detail=f"'{body.package_dir}' is not a directory")
    return _run_gate(package_path)


@app.post("/packages", response_model=PackageOut, status_code=201)
def publish_package(
    body: PublishRequest,
    actor: Annotated[Identity, Depends(require_any_role(Role.ANALYST))],
    store: Annotated[PackageStore, Depends(get_store)],
) -> PackageOut:
    package_path = Path(body.package_dir)
    if not package_path.is_dir():
        raise HTTPException(status_code=400, detail=f"'{body.package_dir}' is not a directory")
    try:
        record = store.publish(package_path, actor=actor)
    except ImmutabilityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return package_record_to_out(record)


@app.post("/packages/{package_id}/review", response_model=PackageOut)
def review_package(
    package_id: str,
    body: ReviewRequest,
    actor: Annotated[Identity, Depends(identity_from_request)],
    workflow: Annotated[ReviewWorkflow, Depends(get_workflow)],
) -> PackageOut:
    try:
        record = workflow.transition(
            package_id,
            body.package_version,
            to_status=body.to_status,
            actor=actor,
            reason=body.reason,
        )
    except ReviewPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except StoreError as exc:
        status_code = 404 if "no such package_version" in str(exc) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return package_record_to_out(record)


@app.get("/packages/{package_id}", response_model=PackageOut)
def get_package(
    package_id: str,
    store: Annotated[PackageStore, Depends(get_store)],
    _actor: Annotated[Identity, Depends(identity_from_request)],
    version: str | None = Query(default=None, description="Specific package_version; omit for the latest"),
) -> PackageOut:
    record = store.get(package_id, version)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no such package: {package_id}")
    return package_record_to_out(record)


@app.get("/packages/{package_id}/audit", response_model=list[AuditEntryOut])
def get_package_audit(
    package_id: str,
    store: Annotated[PackageStore, Depends(get_store)],
    _actor: Annotated[Identity, Depends(identity_from_request)],
    version: str = Query(description="package_version to fetch the audit trail for"),
) -> list[AuditEntryOut]:
    entries = store.audit_trail(package_id, version)
    return [
        AuditEntryOut(
            from_status=e.from_status,
            to_status=e.to_status,
            actor_id=e.actor_id,
            actor_roles=e.actor_roles,
            reason=e.reason,
            ts=e.ts,
        )
        for e in entries
    ]


@app.get("/packages", response_model=ListResponse)
def list_packages(
    store: Annotated[PackageStore, Depends(get_store)],
    _actor: Annotated[Identity, Depends(identity_from_request)],
    profile: str | None = None,
    status: str | None = None,
    owner: str | None = Query(default=None, description="Matches owners.analyst.id or owners.reviewer.id"),
    as_of_from: str | None = Query(default=None, description="ISO-8601 lower bound (inclusive) on as_of"),
    as_of_to: str | None = Query(default=None, description="ISO-8601 upper bound (inclusive) on as_of"),
    query: str | None = Query(default=None, description="Free-text substring match against title"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> ListResponse:
    filt = ListFilter(
        profile=profile,
        status=status,
        owner=owner,
        as_of_from=as_of_from,
        as_of_to=as_of_to,
        query=query,
        page=page,
        page_size=page_size,
    )
    result = store.list(filt)
    return ListResponse(
        items=[package_record_to_out(r) for r in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
