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

from ap_api.deps import (
    get_index,
    get_llm_client,
    get_proposal_notifier,
    get_proposal_store,
    get_proposal_workflow,
    get_store,
    get_workflow,
    reindex_after_transition,
)
from ap_auth.identity import Identity
from ap_console.deps import (
    ConsoleAuthRequired,
    ConsoleCsrfInvalid,
    console_csrf_token,
    get_console_identity,
    verify_console_csrf,
)
from ap_console.gate_report import render_gate_report_html
from ap_index.index_store import IndexStore
from ap_manager_bot.llm_client import LLMClient
from ap_planner_bot.analytics import build_snapshot, compute_corpus_analytics
from ap_planner_bot.detectors import Finding, run_all_detectors
from ap_planner_bot.scan import scan_corpus
from ap_planner_bot.snapshot_store import append_snapshot, read_snapshots
from ap_planner_bot.sweep import run_sweep
from ap_proposals.kinds import ProposalValidationError
from ap_proposals.notify import ProposalNotifier
from ap_proposals.store import ListFilter as ProposalListFilter
from ap_proposals.store import ProposalStore, ProposalStoreError
from ap_proposals.workflow import ProposalPolicyError, ProposalWorkflow
from ap_registry.profile_registry import ProfileRegistry
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


def _citation_review_context(store: PackageStore, package_id: str, *, error: str | None = None) -> dict:
    """Looks up the package's CURRENT status fresh from the store - no version pinned, so this
    always reads the most recently published version's live status, never the (possibly stale)
    version a chat citation happened to point at. Backs both `citation_review_actions` (initial
    render) and `console_review_action`'s `source="chat"` branch (re-render after a decision)."""
    record = store.get(package_id)
    return {"package_id": package_id, "record": record, "error": error}


@router.get("/packages/{package_id}/review-actions", response_class=HTMLResponse)
def citation_review_actions(
    request: Request,
    package_id: str,
    identity: Annotated[Identity, Depends(get_console_identity)],
    store: Annotated[PackageStore, Depends(get_store)],
) -> HTMLResponse:
    """NC.3: the Ask tab's citation rendering (`base.html`'s `htmx:sseBeforeMessage` handler)
    inserts one small `hx-get`-wired element per citation that loads this partial on `load` (see
    that handler's `htmx.process` call - htmx never auto-scans programmatically-inserted markup).
    Renders inline approve/reject buttons only when the package's live status (not the citation's
    redacted-at-index-time chunk) reads `in_review`; otherwise renders nothing. This is purely a
    read + a template branch - the buttons themselves post to the exact same
    `console_review_action` route below (`source=chat`), so the actual transition, CSRF check, and
    policy enforcement are identical to the review queue's. `ManagerBot` is not involved at all:
    this route isn't reachable from the chat/tool loop, only from a human clicking in the console."""
    ctx = _citation_review_context(store, package_id)
    return templates.TemplateResponse(
        request, "_citation_review_actions.html", {"csrf_token": console_csrf_token(request), **ctx}
    )


@router.post("/packages/{package_id}/review", response_class=HTMLResponse)
def console_review_action(
    request: Request,
    package_id: str,
    identity: Annotated[Identity, Depends(get_console_identity)],
    workflow: Annotated[ReviewWorkflow, Depends(get_workflow)],
    store: Annotated[PackageStore, Depends(get_store)],
    index: Annotated[IndexStore, Depends(get_index)],
    package_version: Annotated[str, Form()],
    to_status: Annotated[str, Form()],
    reason: Annotated[str | None, Form()] = None,
    source: Annotated[str, Form()] = "queue",
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
    from a JSON body. On success, `reindex_after_transition` (C12 reindex-wiring fix - see
    ap_api.deps's docstring) re-derives the package's C4 index membership from its new status,
    same call the JSON `POST /packages/{id}/review` route now makes.

    NC.3: the Ask tab's citation approve/reject buttons (`_citation_review_actions.html`) post to
    this exact route too, with a hidden `source=chat` field - same `ReviewWorkflow.transition` call,
    same CSRF/policy handling, only the response partial differs (a small citation-scoped fragment
    instead of the whole queue table), so a decided package's buttons in the Ask tab disappear the
    same way a decided row drops out of the review queue. `source` never changes what's allowed to
    happen, only what's rendered afterward."""
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
    else:
        reindex_after_transition(store, index, package_id, package_version)

    if source == "chat":
        ctx = _citation_review_context(store, package_id, error=error)
        return templates.TemplateResponse(
            request, "_citation_review_actions.html", {"csrf_token": console_csrf_token(request), **ctx}
        )

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
    package_store: Annotated[PackageStore, Depends(get_store)],
    index: Annotated[IndexStore, Depends(get_index)],
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
    notifier: Annotated[ProposalNotifier | None, Depends(get_proposal_notifier)],
    status: str = "pending_hitl",
    kind: str | None = None,
) -> HTMLResponse:
    """"Run planner sweep" button target - wired to the real C6 drafting service (`fathm-p4-sweep`:
    `ap_planner_bot.scan`/`detectors`/`service`). Runs synchronously in-request (design report
    section 5.1/5.2: a full corpus scan + draft pass is seconds at pilot scale), under the console
    session's own identity rather than a service identity - "session identity when triggered from
    the console" per that same section. `llm_client` is a `Depends(get_llm_client)` parameter (not
    a direct call) so `app.dependency_overrides[get_llm_client]` reaches it in tests, matching every
    other store/workflow dependency in this module and `ap_api.chat_routes`'s own use of the same
    dependency - a misconfigured deployment (no `ANTHROPIC_API_KEY`) fails the same way a chat
    request already does, not a new failure mode introduced here. CSRF is still verified first
    since it's a POST reachable via the ambient session cookie."""
    error = None
    try:
        verify_console_csrf(request)
    except ConsoleCsrfInvalid:
        error = "Security token expired or missing - refresh the page and try again."

    notice = None
    if error is None:
        result = run_sweep(
            store=package_store,
            index=index,
            proposal_store=store,
            llm_client=llm_client,
            identity=identity,
            notifier=notifier,
        )
        discarded = sum(result.discarded.values())
        notice = (
            f"Planner sweep: {len(result.created) + discarded} finding(s) scanned, "
            f"{len(result.created)} proposal(s) created"
            + (f", {discarded} discarded ({result.discarded})" if discarded else "")
            + "."
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
    """Proposal-decision-history view: renders every decided proposal (approved/rejected/
    withdrawn) from the proposal audit trail. Distinct from `GET /standard/versions`
    (`ap_api/standard_routes.py`), which reports the registry's own version/changelog state
    directly - this page is proposal-centric (why a decision was made), that route is
    registry-centric (what the current rules are); neither substitutes for the other.

    P5.3 extends this page (rather than a separate "registry state" screen, per the phase-5
    report's §5.3 instruction) with the current pointer version and seed state per profile,
    reading the same `ProfileRegistry` `standard_routes.get_standard_versions` does."""
    result = store.list(ProposalListFilter(page=1, page_size=200))
    decided = [r for r in result.items if r.status != "pending_hitl"]
    decided.sort(key=lambda r: r.decided_at or "", reverse=True)
    registry = ProfileRegistry(store.root)
    profiles = [
        {"name": name, "current_version": registry.current_version(name), "seeded": registry.is_seeded(name)}
        for name in registry.names()
    ]
    return _render(request, "standard_changelog.html", identity=identity, items=decided, registry_profiles=profiles)


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
    record (the real field `ap_proposals` stores it under) rather than computing anything itself.
    The dry-run engine and its API trigger (`ProposalWorkflow.record_dry_run`,
    `POST /proposals/{id}/dry-run`) exist and populate this field for real - but this button isn't
    wired to call it, so `dry_run_json` here reflects whatever the API route (or a direct
    `record_dry_run` call) has already recorded, never what this button itself computes. Wiring
    this button to trigger a run is a separate, still-open UI task; this same rendering path picks
    up real results with no template changes once it lands."""
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
            "dry_run_error": error,
        },
    )


#: Status vocabulary these queue-depth counts read against - matches ap_review/ap_proposals' live
#: workflow states (see _STATUSES / _PROPOSAL_STATUSES above).
_REVIEW_QUEUE_STATUS = "in_review"
_PROPOSAL_QUEUE_STATUS = "pending_hitl"


def _dashboard_tier1_context(store: PackageStore, proposal_store: ProposalStore) -> dict:
    """Instant store stats (design report section 5.2 tier 1) - plain SQL, no corpus scan.
    `PackageStore.stats()` itself never selects `analyst_id`/`reviewer_id` (see its docstring);
    the two queue-depth counts below reuse the exact `ListFilter`/`.total` pattern
    `_review_queue_context`/`_proposal_queue_context` already use elsewhere in this module, not a
    new query shape."""
    return {
        "store_stats": store.stats(),
        "review_queue_depth": store.list(ListFilter(status=_REVIEW_QUEUE_STATUS, page_size=1)).total,
        "proposal_queue_depth": proposal_store.list(
            ProposalListFilter(status=_PROPOSAL_QUEUE_STATUS, page_size=1)
        ).total,
    }


def _snapshot_to_tier2_rows(snapshot: dict[str, Any] | None) -> dict:
    """Reshapes one `ap_planner_bot.snapshot_store` row - or a live `build_snapshot(...)` dict,
    same shape - into template-ready rows. Kept as one function so the initial page load (reads
    the latest stored snapshot, no scan) and the "Recompute now" fragment (a freshly-built
    snapshot dict, not yet read back from disk) render through identical markup - see dashboard()
    / dashboard_recompute() below."""
    snapshot = snapshot or {}
    reason_rows = sorted(snapshot.get("reason_code_counts", {}).items(), key=lambda kv: (-kv[1], kv[0]))
    profile_rows = sorted(snapshot.get("profile_version_counts", {}).items())
    return {
        "package_count": snapshot.get("package_count", 0),
        "check_stats": snapshot.get("check_stats", []),
        "reason_code_rows": reason_rows,
        "other_reason_code_share": snapshot.get("other_reason_code_share", 0.0),
        "profile_version_rows": profile_rows,
        "agent_draft_fail_rate": snapshot.get("agent_draft_fail_rate"),
        "as_of": snapshot.get("ts"),
    }


def _dashboard_live_context(
    *, snapshot: dict[str, Any] | None, findings: list[Finding], live: bool, series: list[dict[str, Any]]
) -> dict:
    return {
        "tier2": _snapshot_to_tier2_rows(snapshot),
        "has_data": snapshot is not None,
        "live": live,
        "findings": findings,
        "series": series,
    }


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    identity: Annotated[Identity, Depends(get_console_identity)],
    store: Annotated[PackageStore, Depends(get_store)],
    proposal_store: Annotated[ProposalStore, Depends(get_proposal_store)],
) -> HTMLResponse:
    """Gate-analytics dashboard (design report section 5.2). Tier 1 (store_stats/queue depths) is
    plain SQL, always live. Tier 2/3 render from the latest recorded snapshot
    (`analytics/snapshots.jsonl`, see `ap_planner_bot.snapshot_store`) with no corpus scan on page
    load - the freshness/latency choice the brief calls for. The "Recompute now" button
    (`POST /dashboard/recompute` below) runs a live scan in-request and swaps in fresh numbers."""
    tier1 = _dashboard_tier1_context(store, proposal_store)
    series = read_snapshots(store.root)
    latest = series[-1] if series else None
    live_ctx = _dashboard_live_context(snapshot=latest, findings=[], live=False, series=series)
    return _render(request, "dashboard.html", identity=identity, **tier1, **live_ctx)


@router.post("/dashboard/recompute", response_class=HTMLResponse)
def dashboard_recompute(
    request: Request,
    identity: Annotated[Identity, Depends(get_console_identity)],
    store: Annotated[PackageStore, Depends(get_store)],
) -> HTMLResponse:
    """"Recompute now" button target (same in-request-live-scan precedent as the Standard tab's
    sweep button): reruns `ap_planner_bot.scan.scan_corpus` for real, computes tier-2 analytics
    (`ap_planner_bot.analytics.compute_corpus_analytics`) and the current drift-signal findings
    (`ap_planner_bot.detectors.run_all_detectors`) over that one scan, and appends the resulting
    snapshot to `analytics/snapshots.jsonl` - the same trend-recorder write the weekly sweep makes
    (`ap_planner_bot.sweep.run_sweep`), just triggered on demand. Re-renders only the
    `#dashboard-live` fragment (htmx outerHTML swap) - tier 1's SQL counts don't need recomputing
    on this click, mirroring how the Standard tab's sweep button only swaps its own table."""
    error = None
    try:
        verify_console_csrf(request)
    except ConsoleCsrfInvalid:
        error = "Security token expired or missing - refresh the page and try again."

    if error is None:
        scan = scan_corpus(store)
        analytics = compute_corpus_analytics(scan)
        snapshot = build_snapshot(analytics)
        append_snapshot(store.root, snapshot)
        findings = run_all_detectors(scan)
        live_ctx = _dashboard_live_context(
            snapshot=snapshot, findings=findings, live=True, series=read_snapshots(store.root)
        )
    else:
        series = read_snapshots(store.root)
        latest = series[-1] if series else None
        live_ctx = _dashboard_live_context(snapshot=latest, findings=[], live=False, series=series)

    return templates.TemplateResponse(
        request, "_dashboard_live.html", {"csrf_token": console_csrf_token(request), "error": error, **live_ctx}
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
    from ap_console.admin_routes import router as admin_router

    app.include_router(router)
    app.include_router(admin_router)
    app.add_exception_handler(ConsoleAuthRequired, _redirect_to_login)
    app.mount("/console/static", StaticFiles(directory=str(_STATIC_DIR)), name="console-static")
