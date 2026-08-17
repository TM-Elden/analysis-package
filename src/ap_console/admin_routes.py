"""Admin tab (P5.3, `data/fathm-phase5-readiness/report.md` §5.3 in the firstmate repo): users &
access, index health, settings. Every route here is gated on `Role.ADMIN` via
`ap_console.deps.require_console_admin` (a 403, not a redirect, for an authenticated non-admin -
see that dependency's docstring). Registry state is not a fifth screen here - it extends
`standard_changelog` (`routes.py`), per the design report's "don't build a separate screen"
instruction.

Same patterns as `routes.py` throughout: `_render`/`templates.TemplateResponse` for full pages and
htmx partials, `verify_console_csrf` called explicitly (not by the identity dependency) before any
mutation, `Depends(get_store)`/`Depends(get_auth_store)` so `app.dependency_overrides` reaches every
store constructed through this module (mirrors `console_review_action`'s reasoning verbatim - see
CLAUDE.md's Phase 3 console section).
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ap_api.deps import DEFAULT_INDEX_ROOT, DEFAULT_STORE_ROOT, get_auth_store, get_index, get_store
from ap_auth.identity import Identity, IdentityError, parse_roles
from ap_auth.roles import Role
from ap_auth.store import AuthError, AuthStore, LastAdminError
from ap_console.deps import ConsoleCsrfInvalid, console_csrf_token, require_console_admin, verify_console_csrf
from ap_console.routes import _render, templates
from ap_index.index_store import IndexStore
from ap_index.reindex import reindex_package
from ap_redact.report import read_report
from ap_store.store import ListFilter, PackageStore

router = APIRouter(prefix="/console/admin")

#: KV key `set_setting`/`get_setting` use for the retention edit - shared with the later lifecycle
#: task (`fathm-p5-lifecycle`) reading the same `store_settings` row; see ap_store.db module
#: docstring for the schema-coordination note.
RETENTION_DAYS_KEY = "retention_days"


@router.get("/")
def admin_root() -> RedirectResponse:
    return RedirectResponse(url="/console/admin/users", status_code=303)


# -- users & access ---------------------------------------------------------


def _users_context(auth_store: AuthStore, *, error: str | None = None, notice: str | None = None) -> dict:
    return {
        "users": auth_store.list_users(),
        "roles": list(Role),
        "error": error,
        "notice": notice,
    }


@router.get("/users", response_class=HTMLResponse)
def admin_users(
    request: Request,
    identity: Annotated[Identity, Depends(require_console_admin)],
    auth_store: Annotated[AuthStore, Depends(get_auth_store)],
) -> HTMLResponse:
    return _render(request, "admin_users.html", identity, **_users_context(auth_store))


@router.post("/users", response_class=HTMLResponse)
def admin_create_user(
    request: Request,
    identity: Annotated[Identity, Depends(require_console_admin)],
    auth_store: Annotated[AuthStore, Depends(get_auth_store)],
    user_id: Annotated[str, Form()],
    display_name: Annotated[str, Form()],
    roles: Annotated[list[str], Form()] = [],
    password: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    error = None
    notice = None
    try:
        verify_console_csrf(request)
        role_set = parse_roles(",".join(roles)) if roles else frozenset()
        auth_store.create_user(
            user_id, display_name=display_name, roles=role_set, password=password or None, actor=identity
        )
        notice = f"created user {user_id!r}."
    except ConsoleCsrfInvalid:
        error = "Security token expired or missing - refresh the page and try again."
    except (AuthError, IdentityError) as exc:
        error = str(exc)
    ctx = _users_context(auth_store, error=error, notice=notice)
    return templates.TemplateResponse(
        request, "_admin_users_body.html", {"csrf_token": console_csrf_token(request), **ctx}
    )


def _user_detail_context(
    auth_store: AuthStore, user_id: str, *, error: str | None = None, notice: str | None = None
) -> dict | None:
    user = auth_store.get_user(user_id)
    if user is None:
        return None
    return {
        "user": user,
        "all_roles": list(Role),
        "current_roles": set(parse_roles(user.roles)) if user.roles else set(),
        "sessions": auth_store.list_sessions(user_id),
        "audit_entries": auth_store.audit_trail(user_id),
        "error": error,
        "notice": notice,
    }


@router.get("/users/{user_id}", response_class=HTMLResponse)
def admin_user_detail(
    request: Request,
    user_id: str,
    identity: Annotated[Identity, Depends(require_console_admin)],
    auth_store: Annotated[AuthStore, Depends(get_auth_store)],
) -> HTMLResponse:
    ctx = _user_detail_context(auth_store, user_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"no such user: {user_id}")
    return _render(request, "admin_user_detail.html", identity, **ctx)


def _user_detail_response(
    request: Request, identity: Identity, auth_store: AuthStore, user_id: str, *, error: str | None, notice: str | None
) -> HTMLResponse:
    """Every POST action on the user detail page returns this same partial (htmx `outerHTML`
    swap of `#admin-user-detail-body`), mirroring `console_review_action`'s pattern."""
    ctx = _user_detail_context(auth_store, user_id, error=error, notice=notice)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"no such user: {user_id}")
    return templates.TemplateResponse(
        request, "_admin_user_detail_body.html", {"csrf_token": console_csrf_token(request), **ctx}
    )


@router.post("/users/{user_id}/roles", response_class=HTMLResponse)
def admin_set_roles(
    request: Request,
    user_id: str,
    identity: Annotated[Identity, Depends(require_console_admin)],
    auth_store: Annotated[AuthStore, Depends(get_auth_store)],
    roles: Annotated[list[str], Form()] = [],
) -> HTMLResponse:
    error = None
    notice = None
    try:
        verify_console_csrf(request)
        role_set = parse_roles(",".join(roles)) if roles else frozenset()
        auth_store.set_roles(user_id, role_set, actor=identity)
        notice = "roles updated."
    except ConsoleCsrfInvalid:
        error = "Security token expired or missing - refresh the page and try again."
    except (AuthError, IdentityError) as exc:
        # Covers LastAdminError too (a subclass of AuthError) - rendered as the same inline flash.
        error = str(exc)
    return _user_detail_response(request, identity, auth_store, user_id, error=error, notice=notice)


@router.post("/users/{user_id}/password", response_class=HTMLResponse)
def admin_reset_password(
    request: Request,
    user_id: str,
    identity: Annotated[Identity, Depends(require_console_admin)],
    auth_store: Annotated[AuthStore, Depends(get_auth_store)],
    password: Annotated[str, Form()],
) -> HTMLResponse:
    error = None
    notice = None
    try:
        verify_console_csrf(request)
        if not password:
            raise AuthError("password must be non-empty")
        auth_store.set_password(user_id, password, actor=identity)
        notice = "password reset."
    except ConsoleCsrfInvalid:
        error = "Security token expired or missing - refresh the page and try again."
    except AuthError as exc:
        error = str(exc)
    return _user_detail_response(request, identity, auth_store, user_id, error=error, notice=notice)


@router.post("/users/{user_id}/disabled", response_class=HTMLResponse)
def admin_set_disabled(
    request: Request,
    user_id: str,
    identity: Annotated[Identity, Depends(require_console_admin)],
    auth_store: Annotated[AuthStore, Depends(get_auth_store)],
    disabled: Annotated[str, Form()],
) -> HTMLResponse:
    error = None
    notice = None
    try:
        verify_console_csrf(request)
        want_disabled = disabled == "1"
        auth_store.set_disabled(user_id, want_disabled, actor=identity)
        notice = "user disabled." if want_disabled else "user enabled."
    except ConsoleCsrfInvalid:
        error = "Security token expired or missing - refresh the page and try again."
    except (AuthError, LastAdminError) as exc:
        error = str(exc)
    return _user_detail_response(request, identity, auth_store, user_id, error=error, notice=notice)


@router.post("/users/{user_id}/tokens", response_class=HTMLResponse)
def admin_issue_token(
    request: Request,
    user_id: str,
    identity: Annotated[Identity, Depends(require_console_admin)],
    auth_store: Annotated[AuthStore, Depends(get_auth_store)],
) -> HTMLResponse:
    error = None
    notice = None
    try:
        verify_console_csrf(request)
        raw = auth_store.create_service_token(user_id, actor=identity)
        # Shown once, same as `ap-auth token` on the CLI - never persisted or logged in the clear.
        notice = f"service-account token issued (copy it now, it will not be shown again): {raw}"
    except ConsoleCsrfInvalid:
        error = "Security token expired or missing - refresh the page and try again."
    except AuthError as exc:
        error = str(exc)
    return _user_detail_response(request, identity, auth_store, user_id, error=error, notice=notice)


@router.post("/users/{user_id}/sessions/{token_hash}/revoke", response_class=HTMLResponse)
def admin_revoke_session(
    request: Request,
    user_id: str,
    token_hash: str,
    identity: Annotated[Identity, Depends(require_console_admin)],
    auth_store: Annotated[AuthStore, Depends(get_auth_store)],
) -> HTMLResponse:
    error = None
    notice = None
    try:
        verify_console_csrf(request)
        auth_store.revoke_session_by_hash(token_hash, actor=identity)
        notice = "session/token revoked."
    except ConsoleCsrfInvalid:
        error = "Security token expired or missing - refresh the page and try again."
    except AuthError as exc:
        error = str(exc)
    return _user_detail_response(request, identity, auth_store, user_id, error=error, notice=notice)


# -- index health (C14 fail-closed visibility) -------------------------------


def _index_health_context(store: PackageStore) -> dict:
    """Every `approved` package whose redaction sidecar says `blocked=True` - the C14 fail-closed
    visibility gap the Phase 3 report flagged and never built (see CLAUDE.md's admin-tab section).
    Pages through the full approved set (bounded corpus at pilot scale, same assumption
    `ap_planner_bot.scan.scan_corpus` already makes) rather than adding a store-level query, since
    "blocked" is redaction-sidecar state, not a `packages` column."""
    blocked: list[dict] = []
    page = 1
    while True:
        result = store.list(ListFilter(status="approved", page=page, page_size=200))
        for record in result.items:
            report = read_report(store.root, record.package_id, record.package_version)
            if report is not None and report.blocked:
                blocked.append({"pkg": record, "report": report})
        if page * result.page_size >= result.total:
            break
        page += 1
    return {"blocked": blocked}


@router.get("/index-health", response_class=HTMLResponse)
def admin_index_health(
    request: Request,
    identity: Annotated[Identity, Depends(require_console_admin)],
    store: Annotated[PackageStore, Depends(get_store)],
) -> HTMLResponse:
    return _render(request, "admin_index_health.html", identity, **_index_health_context(store))


@router.post("/index-health/{package_id}/{package_version}/reindex", response_class=HTMLResponse)
def admin_reindex_package(
    request: Request,
    package_id: str,
    package_version: str,
    identity: Annotated[Identity, Depends(require_console_admin)],
    store: Annotated[PackageStore, Depends(get_store)],
    index: Annotated[IndexStore, Depends(get_index)],
) -> HTMLResponse:
    """"Re-run redaction + reindex" button - calls the real `ap_index.reindex.reindex_package`
    (the same hook the review-decision path calls), not a bespoke redaction re-run. If the package
    is still blocked afterwards (e.g. the secret wasn't actually removed from a republished
    version - packages are immutable, so this is expected until a new version is published) it
    simply stays in the list with its refreshed report."""
    error = None
    try:
        verify_console_csrf(request)
        reindex_package(store=store, index=index, store_root=store.root, package_id=package_id, package_version=package_version)
    except ConsoleCsrfInvalid:
        error = "Security token expired or missing - refresh the page and try again."
    ctx = _index_health_context(store)
    ctx["error"] = error
    return templates.TemplateResponse(
        request, "_index_health_table.html", {"csrf_token": console_csrf_token(request), **ctx}
    )


# -- settings -----------------------------------------------------------------


def _settings_context(store: PackageStore, *, error: str | None = None, notice: str | None = None) -> dict:
    raw = store.get_setting(RETENTION_DAYS_KEY)
    return {
        "retention_days": raw,
        "audit_entries": store.settings_audit_trail(RETENTION_DAYS_KEY),
        "effective_config": {
            "store root": str(DEFAULT_STORE_ROOT),
            "index root": str(DEFAULT_INDEX_ROOT),
            "auth db": os.environ.get("AP_AUTH_DB", "~/.fathm/auth.sqlite3 (default)"),
            "standard registry root (AP_STANDARD_REGISTRY_ROOT)": os.environ.get(
                "AP_STANDARD_REGISTRY_ROOT", "(unset - falls back to repo profiles/)"
            ),
            "manager bot model (AP_MANAGER_BOT_MODEL)": os.environ.get(
                "AP_MANAGER_BOT_MODEL", "claude-sonnet-5 (default)"
            ),
            "chat allowlist path (AP_CHAT_ALLOWLIST_PATH)": os.environ.get(
                "AP_CHAT_ALLOWLIST_PATH", "~/.fathm/chat_telegram_allowlist.json (default)"
            ),
        },
        "error": error,
        "notice": notice,
    }


@router.get("/settings", response_class=HTMLResponse)
def admin_settings(
    request: Request,
    identity: Annotated[Identity, Depends(require_console_admin)],
    store: Annotated[PackageStore, Depends(get_store)],
) -> HTMLResponse:
    return _render(request, "admin_settings.html", identity, **_settings_context(store))


@router.post("/settings", response_class=HTMLResponse)
def admin_set_retention(
    request: Request,
    identity: Annotated[Identity, Depends(require_console_admin)],
    store: Annotated[PackageStore, Depends(get_store)],
    retention_days: Annotated[str, Form()],
) -> HTMLResponse:
    error = None
    notice = None
    try:
        verify_console_csrf(request)
        parsed = int(retention_days)
        if parsed <= 0:
            raise ValueError("retention_days must be a positive integer")
        store.set_setting(RETENTION_DAYS_KEY, str(parsed), actor=identity)
        notice = f"retention_days set to {parsed}."
    except ConsoleCsrfInvalid:
        error = "Security token expired or missing - refresh the page and try again."
    except ValueError as exc:
        error = str(exc)
    ctx = _settings_context(store, error=error, notice=notice)
    return templates.TemplateResponse(
        request, "_admin_settings_body.html", {"csrf_token": console_csrf_token(request), **ctx}
    )
