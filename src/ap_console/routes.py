"""Console routes: login page, package list (filterable), package detail, embedded gate report.

Mounted by `include_console(app)` under the `/console` prefix (except the two routes phase 3.1
already owns at the root - `POST /login` / `POST /logout`, reused as-is per the brief: "posts to
phase 3.1's POST /login"). List/detail read straight from `PackageStore` (the same store
`ap_api.app`'s `GET /packages*` routes use) rather than making an HTTP round-trip back into this
same process - "the console consumes the existing JSON endpoints where convenient but is allowed
to be server-composed pages" (phase-3 report section 5.1).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ap_api.deps import get_store, get_workflow
from ap_auth.identity import Identity
from ap_console.deps import (
    ConsoleAuthRequired,
    ConsoleCsrfInvalid,
    console_csrf_token,
    get_console_identity,
    verify_console_csrf,
)
from ap_console.gate_report import render_gate_report_html
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
