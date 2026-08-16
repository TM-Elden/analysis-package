"""Console-specific auth: reuses `ap_auth.store.AuthStore` (the same session cookie `POST /login`
sets) but resolves to a redirect instead of a 401 JSON body - `ap_api.deps.identity_from_request`
is right for an API client, wrong for a browser tab. `ConsoleAuthRequired` plus the handler
registered in `routes.include_console` is what makes "a logged-out request to any console page
redirects to login" real rather than a per-route `if` (see the SESSION_COOKIE_NAME/CSRF split in
`ap_api.deps` for why an httponly cookie also means the CSRF token must be recomputed server-side,
below).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ap_api.deps import SESSION_COOKIE_NAME, get_auth_store
from ap_auth.csrf import csrf_token_for, csrf_token_matches
from ap_auth.identity import Identity
from ap_auth.store import AuthStore


class ConsoleAuthRequired(Exception):
    """Raised by `get_console_identity` for a missing/invalid/expired session; caught by the
    exception handler registered in `routes.include_console`, which redirects to `/console/login`
    instead of returning JSON - never let this escape as a raw 500."""


class ConsoleCsrfInvalid(Exception):
    """Raised by `verify_console_csrf` for a missing/mismatched X-Csrf header on a state-changing
    console request. Deliberately distinct from `ConsoleAuthRequired`: the session itself is fine
    (a redirect to /console/login would just be confusing for an already-logged-in reviewer), so
    route handlers should catch this and render an inline flash message instead, the same way they
    already handle `ReviewPolicyError` - never let this escape as a raw 403 JSON body either."""


def get_console_identity(
    request: Request,
    auth_store: Annotated[AuthStore, Depends(get_auth_store)],
) -> Identity:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise ConsoleAuthRequired()
    identity = auth_store.identity_for_token(raw_token)
    if identity is None:
        raise ConsoleAuthRequired()
    return identity


def verify_console_csrf(request: Request) -> None:
    """Mirrors `ap_api.deps.identity_from_request`'s CSRF check (same `X-Csrf` header, same
    session-bound token) for console routes that use `get_console_identity` instead - that
    dependency only resolves the session, it never checks CSRF, so any state-changing console
    route (a POST/PUT/PATCH/DELETE reachable via the browser's ambient session cookie) must call
    this itself before mutating anything."""
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    presented = request.headers.get("x-csrf")
    if not raw_token or not csrf_token_matches(raw_token, presented):
        raise ConsoleCsrfInvalid()


def console_csrf_token(request: Request) -> str | None:
    """The `X-Csrf` value the logout button needs. Not read from a JS-visible cookie (the session
    cookie is HttpOnly by design, see ap_auth.csrf) - recomputed server-side from the raw session
    token on every page render, the same deterministic function `POST /login` used once at login."""
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        return None
    return csrf_token_for(raw_token)
