"""FastAPI dependency wiring: shared PackageStore, review policy, and identity extraction.

Identity extraction (`identity_from_request`) reads the `X-Ap-Actor-Id` / `X-Ap-Actor-Roles`
headers - see `ap_auth.identity` module docstring for why this is a documented placeholder, not
authentication, and what phase 3 swaps in underneath it without changing any route handler.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from ap_auth.identity import Identity, IdentityError, parse_roles
from ap_review.policy import ReviewPolicy
from ap_review.workflow import ReviewWorkflow
from ap_store.store import PackageStore

#: Default store root - overridable via AP_STORE_ROOT for tests / alternate deployments. No hosting
#: decision has been made (design doc section 20); this is a local filesystem path because phase 2
#: runs locally (Pi or dev box) by design, not a foreclosure of a future hosted deployment.
DEFAULT_STORE_ROOT = Path(os.environ.get("AP_STORE_ROOT", str(Path.home() / ".fathm" / "ap_store")))


@lru_cache(maxsize=1)
def get_store() -> PackageStore:
    return PackageStore(DEFAULT_STORE_ROOT)


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
    x_ap_actor_id: Annotated[str | None, Header()] = None,
    x_ap_actor_roles: Annotated[str | None, Header()] = None,
) -> Identity:
    if not x_ap_actor_id or not x_ap_actor_roles:
        raise HTTPException(
            status_code=401,
            detail=(
                "X-Ap-Actor-Id and X-Ap-Actor-Roles headers are required to identify the caller "
                "(see ap_auth.identity - phase 2 has no login system yet, this is a placeholder)"
            ),
        )
    try:
        return Identity(id=x_ap_actor_id, roles=parse_roles(x_ap_actor_roles))
    except IdentityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
