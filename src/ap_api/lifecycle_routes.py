"""C12 package lifecycle API: `POST /packages/{id}/supersede`, `POST /packages/{id}/recall`,
`POST /packages/{id}/restore`, `POST /packages/{id}/legal-hold`, `GET /packages/{id}/export`.

Thin routes over `ap_lifecycle.workflow.LifecycleWorkflow`, mirroring `ap_api.app.review_package`'s
error-code mapping exactly (`LifecyclePolicyError` -> 403, a plain `StoreError` -> 404 for "no such
package_version" else 409 for a CAS conflict). Every status-changing route here also calls
`ap_api.deps.reindex_after_transition` after a successful transition - the reindex-wiring fix this
task lands (see that function's docstring and CLAUDE.md's C12 section); `export` is a read and
`legal-hold`/`restore`-to-non-approved don't change index membership either way `reindex_package`
would compute differently, but calling it uniformly after every transition that touches `status`
is simpler to keep correct than reasoning per-route about which ones matter - it's a cheap,
idempotent, sub-second call at this corpus scale (see CLAUDE.md's ap_index section).

No `POST /packages/{id}/purge` route here - purge is console-confirmed and console UI is a
separate, later task (P5.5); `LifecycleWorkflow.purge` is fully implemented and tested at the
workflow/store layer today, callable directly by a future console route or an operator script.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ap_api.deps import get_index, get_lifecycle_workflow, get_store, identity_from_request, reindex_after_transition, require_any_role
from ap_api.schemas import LegalHoldRequest, PackageOut, RecallRequest, RestoreRequest, SupersedeRequest, package_record_to_out
from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_index.index_store import IndexStore
from ap_lifecycle.workflow import LifecyclePolicyError, LifecycleWorkflow
from ap_store.store import PackageStore, StoreError

router = APIRouter()


def _map_store_error(exc: StoreError) -> HTTPException:
    status_code = 404 if "no such package_version" in str(exc) else 409
    return HTTPException(status_code=status_code, detail=str(exc))


@router.post("/packages/{package_id}/supersede", response_model=PackageOut)
def supersede_package(
    package_id: str,
    body: SupersedeRequest,
    actor: Annotated[Identity, Depends(identity_from_request)],
    workflow: Annotated[LifecycleWorkflow, Depends(get_lifecycle_workflow)],
    store: Annotated[PackageStore, Depends(get_store)],
    index: Annotated[IndexStore, Depends(get_index)],
) -> PackageOut:
    try:
        record = workflow.supersede(
            package_id,
            body.package_version,
            successor_package_id=body.successor_package_id,
            successor_package_version=body.successor_package_version,
            actor=actor,
            reason=body.reason,
        )
    except LifecyclePolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except StoreError as exc:
        raise _map_store_error(exc) from exc
    reindex_after_transition(store, index, package_id, body.package_version)
    reindex_after_transition(store, index, body.successor_package_id, body.successor_package_version)
    return package_record_to_out(record)


@router.post("/packages/{package_id}/recall", response_model=PackageOut)
def recall_package(
    package_id: str,
    body: RecallRequest,
    actor: Annotated[Identity, Depends(identity_from_request)],
    workflow: Annotated[LifecycleWorkflow, Depends(get_lifecycle_workflow)],
    store: Annotated[PackageStore, Depends(get_store)],
    index: Annotated[IndexStore, Depends(get_index)],
) -> PackageOut:
    try:
        record = workflow.recall(package_id, body.package_version, actor=actor, reason=body.reason)
    except LifecyclePolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except StoreError as exc:
        raise _map_store_error(exc) from exc
    reindex_after_transition(store, index, package_id, body.package_version)
    return package_record_to_out(record)


@router.post("/packages/{package_id}/restore", response_model=PackageOut)
def restore_package(
    package_id: str,
    body: RestoreRequest,
    actor: Annotated[Identity, Depends(identity_from_request)],
    workflow: Annotated[LifecycleWorkflow, Depends(get_lifecycle_workflow)],
    store: Annotated[PackageStore, Depends(get_store)],
    index: Annotated[IndexStore, Depends(get_index)],
) -> PackageOut:
    try:
        record = workflow.restore(package_id, body.package_version, actor=actor, reason=body.reason)
    except LifecyclePolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except StoreError as exc:
        raise _map_store_error(exc) from exc
    reindex_after_transition(store, index, package_id, body.package_version)
    return package_record_to_out(record)


@router.post("/packages/{package_id}/legal-hold", response_model=PackageOut)
def set_legal_hold(
    package_id: str,
    body: LegalHoldRequest,
    actor: Annotated[Identity, Depends(identity_from_request)],
    workflow: Annotated[LifecycleWorkflow, Depends(get_lifecycle_workflow)],
) -> PackageOut:
    try:
        record = workflow.set_legal_hold(package_id, body.package_version, hold=body.hold, reason=body.reason, actor=actor)
    except LifecyclePolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except StoreError as exc:
        raise _map_store_error(exc) from exc
    return package_record_to_out(record)


@router.get("/packages/{package_id}/export")
def export_package(
    package_id: str,
    _actor: Annotated[Identity, Depends(require_any_role(Role.ANALYST, Role.REVIEWER, Role.STANDARD_APPROVER))],
    store: Annotated[PackageStore, Depends(get_store)],
    version: str,
) -> StreamingResponse:
    """Stream the stored deterministic tar.gz for one package version (C12's "customer can export
    and leave" item, TRUST.md commitment 5). Requires the same elevated role set
    `ap_manager_bot.scoping` already uses for `internal_restricted` content - an export is the full
    raw bytes including unredacted author fields, not the redacted index view."""
    record = store.get(package_id, version)
    # A purged record's blob is gone (PackageStore.purge unlinks it once unreferenced) - treat it
    # as not-found here rather than letting BlobStore.get below raise a raw FileNotFoundError.
    if record is None or record.purged_at is not None:
        raise HTTPException(status_code=404, detail=f"no such package_version: {package_id}/{version}")
    blob = store.blob_store.get(record.blob_sha256)
    filename = f"{package_id}-{version}.tar.gz"
    return StreamingResponse(
        iter([blob]),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
