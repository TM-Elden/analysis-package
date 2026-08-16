"""POST /login, POST /logout - the real C11 browser-session endpoints.

`POST /login` verifies a password against `AuthStore`, issues an opaque server-side session token,
and sets it as an HttpOnly/SameSite=Lax/Secure cookie - see `ap_api.deps.identity_from_request` for
how that cookie is later resolved back to an `Identity`, and `ap_auth.csrf` for why the response
also hands back a `csrf_token` the client must echo on state-changing requests.

`secure=True` requires HTTPS - see CLAUDE.md's C11 auth section for the local-dev/test workaround
(the design doc's `tailscale serve` fronts the real deployment with TLS; tests talk to the app over
an `https://` base URL against FastAPI's TestClient, which never actually opens a socket).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ap_api.deps import SESSION_COOKIE_NAME, get_auth_store, identity_from_request
from ap_api.schemas import LoginRequest, LoginResponse
from ap_auth.csrf import csrf_token_for
from ap_auth.identity import Identity
from ap_auth.store import SESSION_TTL, AuthStore

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    response: Response,
    auth_store: Annotated[AuthStore, Depends(get_auth_store)],
) -> LoginResponse:
    identity = auth_store.verify_login(body.user_id, body.password)
    if identity is None:
        raise HTTPException(status_code=401, detail="invalid user id or password")
    raw_token = auth_store.create_session(identity.id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
    )
    return LoginResponse(
        user_id=identity.id,
        roles=sorted(r.value for r in identity.roles),
        csrf_token=csrf_token_for(raw_token),
    )


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    auth_store: Annotated[AuthStore, Depends(get_auth_store)],
    _actor: Annotated[Identity, Depends(identity_from_request)],
) -> dict[str, str]:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        auth_store.revoke_token(raw_token)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"status": "logged_out"}
