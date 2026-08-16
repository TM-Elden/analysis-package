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

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ap_api.deps import get_store
from ap_auth.identity import Identity
from ap_console.deps import ConsoleAuthRequired, console_csrf_token, get_console_identity
from ap_console.gate_report import render_gate_report_html
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
    )


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
