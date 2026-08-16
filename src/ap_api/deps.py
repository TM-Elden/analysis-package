"""FastAPI dependency wiring: shared PackageStore, review policy, and real C11 identity extraction.

`identity_from_request` resolves a caller's `Identity` from real credentials - a browser session
cookie or an `Authorization: Bearer <token>` service-account token, both backed by
`ap_auth.store.AuthStore` - not the old `X-Ap-Actor-Id` / `X-Ap-Actor-Roles` header placeholder
(removed, not left as a fallback; see `ap_auth.identity` module docstring and CLAUDE.md).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from ap_auth.csrf import csrf_token_matches
from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_auth.store import DEFAULT_AUTH_DB, AuthStore
from ap_review.policy import ReviewPolicy
from ap_review.workflow import ReviewWorkflow
from ap_store.store import PackageStore

#: Default store root - overridable via AP_STORE_ROOT for tests / alternate deployments. No hosting
#: decision has been made (design doc section 20), this is a local filesystem path because phase 2
#: runs locally (Pi or dev box) by design, not a foreclosure of a future hosted deployment.
DEFAULT_STORE_ROOT = Path(os.environ.get("AP_STORE_ROOT", str(Path.home() / ".fathm" / "ap_store")))

#: Name of the browser session cookie set by POST /login. HttpOnly + SameSite=Lax + Secure - see
#: ap_api/auth_routes.py::login.
SESSION_COOKIE_NAME = "ap_session"

#: HTTP methods that mutate state and therefore require the CSRF header when the caller
#: authenticated via cookie (bearer-token callers are exempt - see identity_from_request below).
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@lru_cache(maxsize=1)
def get_store() -> PackageStore:
    return PackageStore(DEFAULT_STORE_ROOT)


@lru_cache(maxsize=1)
def get_auth_store() -> AuthStore:
    db_path = Path(os.environ.get("AP_AUTH_DB", str(DEFAULT_AUTH_DB)))
    return AuthStore(db_path)


def get_review_policy() -> ReviewPolicy:
    """Policy knobs, env-overridable (AP_GATE_BEFORE_REVIEW / AP_ALLOW_SELF_REVIEW); defaults match
    ap_review.policy.ReviewPolicy's own documented defaults (gate required, distinct reviewer required).
    """
    return ReviewPolicy(
        gate_before_review=os.environ.get("AP_GATE_BEFORE_REVIEW", "true").strip().lower() != "false",
        allow_self_review=os.environ.get("AP_ALLOW_SELF_REVIEW", "false").strip().lower() == "true",
    )


def get_workflow(store: Annotated[PackageStore, Depends(get_store)]) -> ReviewWorkflow:
    """Takes `store` as a FastAPI dependency (not a direct get_store() call) so that overriding
    `app.dependency_overrides[get_store]` (e.g. in tests, to point at a temp store) also redirects
    every ReviewWorkflow built through this function - a plain internal call would bypass the
    override entirely, since FastAPI only rewires dependencies it resolves itself."""
    return ReviewWorkflow(store=store, policy=get_review_policy())


def identity_from_request(
    request: Request,
    auth_store: Annotated[AuthStore, Depends(get_auth_store)],
) -> Identity:
    """Resolves the caller's Identity from a bearer token or a session cookie - every route that
    needs a caller depends on this (see ap_api/app.py). Bearer tokens are checked first: a service
    account presenting `Authorization: Bearer <token>` is never subject to the CSRF check below
    (browsers never attach `Authorization` headers automatically, so there's no ambient-authority
    risk to defend against for that path - see ap_auth.csrf module docstring).
    """
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[len("bearer "):].strip()
        identity = auth_store.identity_for_token(token) if token else None
        if identity is None:
            raise HTTPException(status_code=401, detail="invalid, expired, or revoked bearer token")
        return identity

    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(
            status_code=401,
            detail="no session cookie or Authorization: Bearer token - log in via POST /login, or "
            "use a service-account bearer token for CI/agent callers",
        )
    identity = auth_store.identity_for_token(raw_token)
    if identity is None:
        raise HTTPException(status_code=401, detail="session is invalid, expired, or revoked - log in again")

    if request.method in _UNSAFE_METHODS:
        presented = request.headers.get("x-csrf")
        if not csrf_token_matches(raw_token, presented):
            raise HTTPException(
                status_code=403,
                detail="missing or invalid X-Csrf header for this state-changing request (bound to "
                "the session established at login - see the csrf_token returned by POST /login)",
            )
    return identity


def require_any_role(*roles: Role):
    """Dependency factory: 403s unless the resolved Identity holds at least one of `roles` (or
    admin, which Identity.has_role always treats as a bypass). Use for route-level C11 matrix
    enforcement beyond "authenticated at all" - e.g. only analyst/admin may publish. Read-only
    routes intentionally do NOT use this: with no team/company scoping implemented yet (single
    tenant, see CLAUDE.md), any authenticated identity may read - see ap_api/app.py."""

    def _check(actor: Annotated[Identity, Depends(identity_from_request)]) -> Identity:
        if not any(actor.has_role(r) for r in roles):
            wanted = ", ".join(r.value for r in roles)
            raise HTTPException(status_code=403, detail=f"requires one of roles: {wanted} (or admin)")
        return actor

    return _check
