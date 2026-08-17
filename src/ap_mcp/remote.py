"""NC.2 MCP remote mode: env-selected HTTP client so `package_finalize`/`package_submit_review` can
target a store on a different machine, over `POST /packages/upload` and
`POST /packages/{id}/review` (`ap_api`) instead of touching a local `ap_store.PackageStore` -
`data/fathm-native-chat-readiness/report.md` §5.2 in the firstmate repo, "Remote-capable publish
path".

`remote_mode_config()` is the one place both tools check whether remote mode is active
(`AP_API_URL` + `AP_API_TOKEN` both set - either alone is not enough, since a URL with no token has
no way to authenticate and a token with no URL has nowhere to send it). `package_create` /
`package_check` / `override_record` never consult this module - they operate on the planner's own
working tree unconditionally, local mode or not (see CLAUDE.md's NC.2 section for why this split is
deliberate).

Identity in remote mode comes from the bearer token itself (`ap_api.deps.identity_from_request`
resolves it server-side against `AuthStore`) - the `actor_id`/`actor_roles` arguments local mode
requires are not sent and not needed; a client-declared identity would be meaningless against a
real auth boundary.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

from ap_store.blobstore import make_blob


def remote_mode_config() -> tuple[str, str] | None:
    """Returns (api_url, api_token) if both AP_API_URL and AP_API_TOKEN are set, else None - the
    single switch `package_finalize`/`package_submit_review` check to decide local vs. remote."""
    api_url = os.environ.get("AP_API_URL")
    api_token = os.environ.get("AP_API_TOKEN")
    if api_url and api_token:
        return api_url.rstrip("/"), api_token
    return None


class RemoteApiError(Exception):
    """Raised on a non-2xx response from the remote API - message is planner-serving (the remote
    server's own detail text), not a raw httpx exception."""


class RemoteApiClient:
    """Thin wrapper over `httpx.Client` - one bearer-authenticated client per call, mirroring
    `ap_manager_bot.llm_client.AnthropicHTTPClient`'s injectable-`transport` pattern so tests can
    point this at a real (TestClient-backed) FastAPI app instead of the network - see
    `tests/test_mcp_remote_mode.py`."""

    def __init__(self, base_url: str, token: str, *, transport: httpx.BaseTransport | None = None, timeout: float = 30.0):
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {token}"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RemoteApiClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def publish(self, package_dir: Path | str) -> dict[str, Any]:
        """POST /packages/upload: pack package_dir the exact way ap_store.blobstore already does
        (same deterministic tar.gz shape the store's own blobs use) and upload it."""
        blob = make_blob(Path(package_dir))
        resp = self._client.post("/packages/upload", content=blob, headers={"Content-Type": "application/gzip"})
        if resp.status_code >= 400:
            raise RemoteApiError(f"remote publish failed ({resp.status_code}): {_error_detail(resp)}")
        return resp.json()

    def submit_review(self, package_id: str, package_version: str) -> dict[str, Any]:
        """POST /packages/{id}/review with to_status=in_review - the same transition
        package_submit_review's local mode drives directly through ReviewWorkflow."""
        resp = self._client.post(
            f"/packages/{package_id}/review",
            json={"package_version": package_version, "to_status": "in_review"},
        )
        if resp.status_code >= 400:
            raise RemoteApiError(f"remote submit_review failed ({resp.status_code}): {_error_detail(resp)}")
        return resp.json()


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text
    return str(body.get("detail", body)) if isinstance(body, dict) else str(body)
