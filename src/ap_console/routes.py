"""Console routes: login page, package list (filterable), package detail, embedded gate report.

Mounted by `include_console(app)` under the `/console` prefix (except the two routes phase 3.1
already owns at the root - `POST /login` / `POST /logout`, reused as-is per the brief: "posts to
phase 3.1's POST /login"). List/detail read straight from `PackageStore` (the same store
`ap_api.app`'s `GET /packages*` routes use) rather than making an HTTP round-trip back into this
same process - "the console consumes the existing JSON endpoints where convenient but is allowed
to be server-composed pages" (phase-3 report section 5.1).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ap_api.deps import get_proposal_store, get_proposal_workflow, get_store, get_workflow
from ap_auth.identity import Identity
from ap_console.deps import (
    ConsoleAuthRequired,
    ConsoleCsrfInvalid,
    console_csrf_token,
    get_console_identity,
    verify_console_csrf,
)
from ap_console.gate_report import render_gate_report_html
from ap_proposals.kinds import ProposalValidationError
from ap_proposals.store import ListFilter as ProposalListFilter
from ap_proposals.store import ProposalStore, ProposalStoreError
from ap_proposals.workflow import ProposalPolicyError, ProposalWorkflow
from ap_review.workflow import ReviewPolicyError, ReviewWorkflow
from ap_store.store import ListFilter, PackageStore, StoreError

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/console")

#: Status vocabulary for the filter dropdown - matches ap_review.workflow's live set.
_STATUSES = ["draft", "in_review", "approved", "rejected"]


def _render(request: Request, template_name: str, identity: Identity | None, **context) -> HTMLResponse:
    ctx = {
        "identity": identity,
        "csrf_token": console_csrf_token(request) if identity else None,
        **context,
    }
    return templates.TemplateResponse(request, template_name, ctx)


@router.get("/")
def console_root() -> RedirectResponse:
    return RedirectResponse(url="/console/packages", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return _render(request, "login.html", identity=None)


def _list_page_context(
    store: PackageStore,
    *,
    status: str | None,
    profile: str | None,
    as_of_from: str | None,
    as_of_to: str | None,
    query: str | None,
    page: int,
) -> dict:
    filt = ListFilter(
        status=status or None,
        profile=profile or None,
        as_of_from=as_of_from or None,
        as_of_to=as_of_to or None,
        query=query or None,
        page=page,
        page_size=25,
    )
    result = store.list(filt)
    page_count = max(1, math.ceil(result.total / result.page_size))
    return {
        "items": result.items,
        "total": result.total,
        "page": result.page,
        "page_count": page_count,
        "status": status,
        "profile": profile,
        "as_of_from": as_of_from,
        "as_of_to": as_of_to,
        "query": query,
        "statuses": _STATUSES,
    }


@router.get("/packages", response_class=HTMLResponse)
def packages_list(
    request: Request,
    identity: Annotated[Identity, Depends(get_console_identity)],
    store: Annotated[PackageStore, Depends(get_store)],
    status: str | None = None,
    profile: str | None = None,
    as_of_from: str | None = None,
    as_of_to: str | None = None,
    query: str | None = None,
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    ctx = _list_page_context(
        store, status=status, profile=profile, as_of_from=as_of_from, as_of_to=as_of_to, query=query, page=page
    )
    return _render(request, "packages_list.html", identity=identity, **ctx)


@router.get("/packages/table", response_class=HTMLResponse)
def packages_table(
    request: Request,
    identity: Annotated[Identity, Depends(get_console_identity)],
    store: Annotated[PackageStore, Depends(get_store)],
    status: str | None = None,
    profile: str | None = None,
    as_of_from: str | None = None,
    as_of_to: str | None = None,
    query: str | None = None,
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    """htmx partial: the filter form in packages_list.html re-GETs this on every change and swaps
    it in for #packages-table - no full-page reload for list filtering (per the brief's htmx use)."""
    ctx = _list_page_context(
        store, status=status, profile=profile, as_of_from=as_of_from, as_of_to=as_of_to, query=query, page=page
    )
    return templates.TemplateResponse(request, "_packages_table.html", ctx)


def _review_queue_context(store: PackageStore, *, error: str | None = None) -> dict:
    """In-review packages, oldest-first-ish per the store's default ordering - a queue, not the
    general filterable list, so no pagination controls: the whole point (per the phase-3 report's
    section 4/6 "first genuinely demoable piece") is a reviewer sees everything waiting at a glance.
    """
    result = store.list(ListFilter(status="in_review", page=1, page_size=200))
    return {"items": result.items, "total": result.total, "error": error}


@router.get("/review-queue", response_class=HTMLResponse)
def review_queue(
    request: Request,
    identity: Annotated[Identity, Depends(get_console_identity)],
    store: Annotated[PackageStore, Depends(get_store)],
) -> HTMLResponse:
    ctx = _review_queue_context(store)
    return _render(request, "review_queue.html", identity=identity, **ctx)


@router.post("/packages/{package_id}/review", response_class=HTMLResponse)
def console_review_action(
    request: Request,
    package_id: str,
    identity: Annotated[Identity, Depends(get_console_identity)],
    workflow: Annotated[ReviewWorkflow, Depends(get_workflow)],
    store: Annotated[PackageStore, Depends(get_store)],
    package_version: Annotated[str, Form()],
    to_status: Annotated[str, Form()],
    reason: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    """The queue's approve/reject buttons post here (htmx, `hx-target="#review-queue-table"
    hx-swap="outerHTML"`) - calls the real `ReviewWorkflow.transition` (same policy: gate-before-
    review, distinct-reviewer, reject-requires-reason) and re-renders the queue table in place, so
    a decided package simply drops out of the list rather than needing a page reload. Identity
    resolution goes through `get_console_identity` (missing/expired session -> redirect to
    /console/login, same as every other console route) rather than `ap_api.deps.identity_from_request`
    (which 401/403s with a raw JSON body meant for an API client); since that dependency only
    resolves the session and never checks CSRF, `verify_console_csrf` does that check explicitly
    here. A `ConsoleCsrfInvalid` or `ReviewPolicyError`/`StoreError` (self-review, missing gate
    pass, empty reject reason, wrong role, stale CSRF token) is caught here and rendered as an
    inline flash message on the still-open queue - never a raw 500/403 the reviewer has to decode
    from a JSON body."""
    error = None
    try:
        verify_console_csrf(request)
        workflow.transition(
            package_id,
            package_version,
            to_status=to_status,
            actor=identity,
            reason=reason,
        )
    except ConsoleCsrfInvalid:
        error = "Security token expired or missing - refresh the page and try again."
    except (ReviewPolicyError, StoreError) as exc:
        error = str(exc)
    ctx = _review_queue_context(store, error=error)
    return templates.TemplateResponse(request, "_review_queue_table.html", {"csrf_token": console_csrf_token(request), **ctx})


#: Status vocabulary for the Standard tab's tabs - matches ap_proposals.workflow's live set.
_PROPOSAL_STATUSES = ["pending_hitl", "approved", "rejected", "withdrawn"]
_PROPOSAL_KINDS = ["standard_change", "profile_change", "reason_code_add", "check_add"]


def _evidence_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    """Evidence is a free-form dict (`ap_proposals.models.ProposalRecord.evidence()`) - today's
    only producer (the P4 sweep detectors) writes `{"package_ids": [...]}`, so that's rendered as
    real links into the existing package detail pages; anything else falls back to a raw count so a
    future evidence shape doesn't silently disappear from the UI."""
    package_ids = evidence.get("package_ids") if isinstance(evidence, dict) else None
    if isinstance(package_ids, list) and package_ids:
        return {"package_ids": package_ids, "count": len(package_ids)}
    return {"package_ids": [], "count": len(evidence) if isinstance(evidence, dict) else 0}


def _diff_view(diff: dict[str, Any]) -> dict[str, Any]:
    """Generic per-kind diff rendering (task brief: "a reasonable generic rendering ... is fine if
    per-kind polish isn't available yet"): a before/after column pair when the diff has both keys
    (profile_change's shape today), else a raw pretty-printed JSON fallback that works for any kind,
    including the ones the drafting bot hasn't started producing real content for yet."""
    if isinstance(diff, dict) and "before" in diff and "after" in diff:
        extra = {k: v for k, v in diff.items() if k not in ("before", "after")}
        return {
            "mode": "before_after",
            "before": json.dumps(diff.get("before"), indent=2, sort_keys=True),
            "after": json.dumps(diff.get("after"), indent=2, sort_keys=True),
            "extra": json.dumps(extra, indent=2, sort_keys=True) if extra else None,
        }
    return {"mode": "raw", "raw": json.dumps(diff, indent=2, sort_keys=True)}


def _proposal_queue_context(
    store: ProposalStore, *, status: str | None, kind: str | None, notice: str | None = None
) -> dict:
    filt = ProposalListFilter(status=status or None, kind=kind or None, page=1, page_size=200)
    result = store.list(filt)
    return {
        "items": [(r, _evidence_summary(r.evidence())) for r in result.items],
        "total": result.total,
        "status": status,
        "kind": kind,
        "statuses": _PROPOSAL_STATUSES,
        "kinds": _PROPOSAL_KINDS,
        "notice": notice,
    }


@router.get("/standard", response_class=HTMLResponse)
def standard_queue(
    request: Request,
    identity: Annotated[Identity, Depends(get_console_identity)],
    store: Annotated[ProposalStore, Depends(get_proposal_store)],
    status: str = "pending_hitl",
    kind: str | None = None,
) -> HTMLResponse:
    ctx = _proposal_queue_context(store, status=status, kind=kind)
    return _render(request, "standard_queue.html", identity=identity, **ctx)


@router.get("/standard/table", response_class=HTMLResponse)
def standard_table(
    request: Request,
    identity: Annotated[Identity, Depends(get_console_identity)],
    store: Annotated[ProposalStore, Depends(get_proposal_store)],
    status: str = "pending_hitl",
    kind: str | None = None,
) -> HTMLResponse:
    """htmx partial: the status/kind tabs re-GET this and swap it in for #proposal-queue-table,
    mirroring `packages_table`'s pattern above."""
    ctx = _proposal_queue_context(store, status=status, kind=kind)
    return templates.TemplateResponse(request, "_proposal_queue_table.html", ctx)


@router.post("/standard/sweep", response_class=HTMLResponse)
def standard_sweep(
    request: Request,
    identity: Annotated[Identity, Depends(get_console_identity)],
    store: Annotated[ProposalStore, Depends(get_proposal_store)],
    status: str = "pending_hitl",
    kind: str | None = None,
) -> HTMLResponse:
    """"Run planner sweep" button target. The drafting bot (`fathm-p4-sweep`) that would actually
    scan the corpus and create proposals is a separate, not-yet-built task (see this task's brief) -
    this route is a documented no-op rather than a fake success, so the button is honestly wired to
    something real today and only needs its body swapped for a real call once that bot lands. CSRF
    is still verified since it's a POST reachable via the ambient session cookie."""
    error = None
    try:
        verify_console_csrf(request)
    except ConsoleCsrfInvalid:
        error = "Security token expired or missing - refresh the page and try again."
    notice = (
        None
        if error
        else "Planner sweep is not yet wired up (fathm-p4-sweep is a separate task) - no proposals "
        "were generated. This button will run the real drafting bot once that lands."
    )
    ctx = _proposal_queue_context(store, status=status, kind=kind, notice=notice)
    return templates.TemplateResponse(
        request, "_proposal_queue_table.html", {"csrf_token": console_csrf_token(request), "error": error, **ctx}
    )


@router.get("/standard/changelog", response_class=HTMLResponse)
def standard_changelog(
    request: Request,
    identity: Annotated[Identity, Depends(get_console_identity)],
    store: Annotated[ProposalStore, Depends(get_proposal_store)],
) -> HTMLResponse:
    """Interim version-history view: `GET /standard/versions` (a later task's real changelog
    surface, once the versioned profile registry exists) doesn't exist yet, so this renders every
    decided proposal (approved/rejected/withdrawn) as the closest honest substitute - decisions the
    proposal audit trail can already show today, not a fabricated version list."""
    result = store.list(ProposalListFilter(page=1, page_size=200))
    decided = [r for r in result.items if r.status != "pending_hitl"]
    decided.sort(key=lambda r: r.decided_at or "", reverse=True)
    return _render(request, "standard_changelog.html", identity=identity, items=decided)


@router.get("/standard/proposals/{proposal_id}", response_class=HTMLResponse)
def proposal_detail(
    request: Request,
    proposal_id: str,
    identity: Annotated[Identity, Depends(get_console_identity)],
    store: Annotated[ProposalStore, Depends(get_proposal_store)],
) -> HTMLResponse:
    ctx = _proposal_detail_body_context(store, proposal_id, error=None)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"no such proposal: {proposal_id}")
    return _render(request, "standard_proposal_detail.html", identity=identity, **ctx)


def _proposal_detail_body_context(store: ProposalStore, proposal_id: str, *, error: str | None) -> dict | None:
    record = store.get(proposal_id)
    if record is None:
        return None
    dry_run = record.dry_run()
    return {
        "prop": record,
        "evidence": _evidence_summary(record.evidence()),
        "diff_view": _diff_view(record.diff()),
        "edited_diff_view": _diff_view(record.edited_diff()) if record.edited_diff() is not None else None,
        "edited_diff_text": json.dumps(record.diff(), indent=2, sort_keys=True),
        "audit_entries": store.audit_trail(proposal_id),
        "dry_run": dry_run,
        "dry_run_text": json.dumps(dry_run, indent=2, sort_keys=True) if dry_run is not None else None,
        "error": error,
    }


@router.post("/standard/proposals/{proposal_id}/decision", response_class=HTMLResponse)
def standard_decision(
    request: Request,
    proposal_id: str,
    identity: Annotated[Identity, Depends(get_console_identity)],
    workflow: Annotated[ProposalWorkflow, Depends(get_proposal_workflow)],
    store: Annotated[ProposalStore, Depends(get_proposal_store)],
    to_status: Annotated[str, Form()],
    reason: Annotated[str | None, Form()] = None,
    edited_diff: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    """The detail page's approve / approve-with-edits / reject forms all post here (htmx,
    `hx-target="#proposal-detail-body" hx-swap="outerHTML"`) - calls the real
    `ProposalWorkflow.decide` (standard_approver role, reject-requires-reason, edited_diff schema
    validation) and re-renders the detail body in place, mirroring `console_review_action` above
    exactly (same CSRF-verified-here-not-in-the-dependency reasoning, same inline-flash-not-raw-error
    handling)."""
    error = None
    parsed_edit: dict | None = None
    try:
        verify_console_csrf(request)
        if edited_diff is not None and edited_diff.strip():
            try:
                parsed_edit = json.loads(edited_diff)
            except json.JSONDecodeError as exc:
                raise ValueError(f"edited diff is not valid JSON: {exc}") from exc
        workflow.decide(proposal_id, to_status=to_status, actor=identity, reason=reason, edited_diff=parsed_edit)
    except ConsoleCsrfInvalid:
        error = "Security token expired or missing - refresh the page and try again."
    except ValueError as exc:
        error = str(exc)
    except (ProposalPolicyError, ProposalValidationError, ProposalStoreError) as exc:
        error = str(exc)

    ctx = _proposal_detail_body_context(store, proposal_id, error=error)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"no such proposal: {proposal_id}")
    return templates.TemplateResponse(
        request, "_proposal_detail_body.html", {"csrf_token": console_csrf_token(request), **ctx}
    )


@router.post("/standard/proposals/{proposal_id}/dry-run", response_class=HTMLResponse)
def standard_dry_run(
    request: Request,
    proposal_id: str,
    identity: Annotated[Identity, Depends(get_console_identity)],
    store: Annotated[ProposalStore, Depends(get_proposal_store)],
) -> HTMLResponse:
    """"Run dry-run" button target. Renders whatever `dry_run_json` already exists on the proposal
    record (the real field `ap_proposals` stores it under) rather than computing anything itself -
    the dry-run engine (`fathm-p4-registry-dryrun`) is a separate, not-yet-built task. Today that
    field is always null, so this honestly reports "not yet available" instead of faking a result;
    once that engine lands and starts populating `dry_run_json` (e.g. via a proposal-store write
    this route triggers), this same rendering path picks up real results with no template changes."""
    error = None
    try:
        verify_console_csrf(request)
    except ConsoleCsrfInvalid:
        error = "Security token expired or missing - refresh the page and try again."
    record = store.get(proposal_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no such proposal: {proposal_id}")
    dry_run = record.dry_run()
    return templates.TemplateResponse(
        request,
        "_dry_run_panel.html",
        {
            "prop": record,
            "dry_run": dry_run,
            "dry_run_text": json.dumps(dry_run, indent=2, sort_keys=True) if dry_run is not None else None,
            "csrf_token": console_csrf_token(request),
            "error": error,
        },
    )


def _owners_rows(owners: dict) -> list[tuple[str, str | None]]:
    rows: list[tuple[str, str | None]] = []
    for role, value in owners.items():
        owner_id = value.get("id") if isinstance(value, dict) else value
        rows.append((role, owner_id))
    return rows


@router.get("/packages/{package_id}", response_class=HTMLResponse)
def package_detail(
    request: Request,
    package_id: str,
    identity: Annotated[Identity, Depends(get_console_identity)],
    store: Annotated[PackageStore, Depends(get_store)],
    version: str | None = Query(default=None, description="Specific package_version; omit for the latest"),
) -> HTMLResponse:
    record = store.get(package_id, version)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no such package: {package_id}")
    return _render(
        request,
        "package_detail.html",
        identity=identity,
        pkg=record,
        owners_rows=_owners_rows(record.owners()),
        audit_entries=store.audit_trail(record.package_id, record.package_version),
    )


@router.get("/chat", response_class=HTMLResponse)
def chat_page(
    request: Request,
    identity: Annotated[Identity, Depends(get_console_identity)],
) -> HTMLResponse:
    """The P3.7 query panel shell: a message form plus an empty turn list. Each submitted question
    is rendered by `chat_turn` below as an htmx-swapped-in SSE-connected fragment - this page itself
    holds no chat state, so a reload just clears the transcript (no server-side session log)."""
    return _render(request, "chat.html", identity=identity)


@router.get("/chat/turn", response_class=HTMLResponse)
def chat_turn(
    request: Request,
    identity: Annotated[Identity, Depends(get_console_identity)],
    question: str = Query(..., min_length=1, max_length=2000),
) -> HTMLResponse:
    """htmx partial: the chat form GETs this on submit and appends the result to the transcript
    (`hx-swap="beforeend"`, see chat.html). The fragment itself does no LLM work - it wires an
    `hx-ext="sse"` container at `/chat/manager/stream` (ap_api.chat_routes, root-mounted, not under
    `/console`) so the browser's own EventSource carries the session cookie for auth. This route
    stays a thin question-in-fragment-out echo; the streaming and citation contract live entirely in
    ap_api/ap_manager_bot, per the ap_console/ap_api module boundary in CLAUDE.md."""
    return templates.TemplateResponse(request, "_chat_turn.html", {"question": question})


@router.get("/packages/{package_id}/gate-report", response_class=HTMLResponse)
def package_gate_report(
    package_id: str,
    _identity: Annotated[Identity, Depends(get_console_identity)],
    store: Annotated[PackageStore, Depends(get_store)],
    version: str | None = Query(default=None, description="Specific package_version; omit for the latest"),
) -> HTMLResponse:
    """Raw gate-report HTML (own <html> document, per ap_gate.report.html_report) - embedded via
    <iframe> in package_detail.html and also linkable standalone. Reuses the same renderer the L1
    gate itself uses; see ap_console.gate_report."""
    record = store.get(package_id, version)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no such package: {package_id}")
    try:
        html = render_gate_report_html(store, record.package_id, record.package_version)
    except StoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return HTMLResponse(content=html)


async def _redirect_to_login(request: Request, _exc: ConsoleAuthRequired) -> RedirectResponse:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return RedirectResponse(url=f"/console/login?next={next_path}", status_code=303)


def include_console(app: FastAPI) -> None:
    """Single mount point `ap_api.app` calls: routes + the auth-redirect handler + the vendored
    htmx static file. Kept as one function (rather than `app.include_router` scattered at the call
    site) so the module boundary from CLAUDE.md's console section stays a one-line integration."""
    app.include_router(router)
    app.add_exception_handler(ConsoleAuthRequired, _redirect_to_login)
    app.mount("/console/static", StaticFiles(directory=str(_STATIC_DIR)), name="console-static")
