"""NC.2 MCP remote mode: package_finalize/package_submit_review call a real HTTP API
(`ap_api.app.app`, via a TestClient-backed transport - not mocked at the transport layer only)
instead of a local store when AP_API_URL/AP_API_TOKEN are set; package_create/package_check/
override_record stay local regardless. See ap_mcp/remote.py and CLAUDE.md's NC.2 section.

Driven through `ap_mcp.server.handle_request` (real JSON-RPC `tools/call` messages), same dispatch
path tests/test_mcp_e2e_authoring_loop.py uses for local mode - this is the remote-mode sibling of
that test.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import ap_api.deps as deps
import ap_mcp.tools as mcp_tools
from ap_api.app import app
from ap_auth.roles import Role
from ap_auth.store import AuthStore
from ap_mcp.remote import RemoteApiClient
from ap_mcp.server import handle_request
from ap_store.store import PackageStore


def _call(name: str, arguments: dict, *, msg_id: int) -> dict:
    resp = handle_request(
        {"jsonrpc": "2.0", "id": msg_id, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    )
    assert resp is not None
    return resp["result"]


def _payload(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


@pytest.fixture()
def remote_api(tmp_path, monkeypatch):
    """A real ap_api FastAPI instance (dependency-overridden to a temp store/auth db, same pattern
    tests/test_api.py uses) plus a bearer token for an analyst - and the AP_API_URL/AP_API_TOKEN
    env vars set so ap_mcp.tools.remote_mode_config() reads them as active. The MCP tools' HTTP
    client is redirected at this same in-process app (no real network) by monkeypatching
    ap_mcp.tools._build_remote_client - the one seam that module exposes for exactly this."""
    store = PackageStore(tmp_path / "store")
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[deps.get_auth_store] = lambda: auth_store
    auth_store.create_user("tom.planner", display_name="Tom", roles=frozenset({Role.ANALYST}), password=None)
    token = auth_store.create_service_token("tom.planner")

    test_client = TestClient(app, base_url="https://testserver")

    monkeypatch.setenv("AP_API_URL", "https://testserver")
    monkeypatch.setenv("AP_API_TOKEN", token)
    monkeypatch.setattr(
        mcp_tools,
        "_build_remote_client",
        lambda api_url, api_token: RemoteApiClient(api_url, api_token, transport=test_client._transport),
    )

    try:
        yield store
    finally:
        app.dependency_overrides.clear()
        store.close()
        auth_store.close()


def test_remote_mode_round_trips_finalize_and_submit_review(remote_api, tmp_path):
    store = remote_api
    pkg_dir = str(tmp_path / "pkg")

    # Local: unaffected by remote-mode env vars.
    create_result = _call(
        "package_create",
        {"dest_dir": pkg_dir, "title": "Remote-mode pack", "analyst_id": "tom.planner"},
        msg_id=1,
    )
    assert create_result["isError"] is False

    check_result = _call("package_check", {"package_dir": pkg_dir}, msg_id=2)
    assert check_result["isError"] is False
    assert '"overall": "pass"' in check_result["content"][0]["text"]

    override_result = _call(
        "override_record",
        {
            "package_dir": pkg_dir,
            "field_path": "supplier_forecast.ACME.BBU-100.week_36_qty",
            "before": 1200,
            "after": 900,
            "reason_code": "HOLD_FOR_PRICE_NEGOTIATION",
            "draft_reason_text": "Draft: hold ~300u off ACME pending price talks",
        },
        msg_id=3,
    )
    assert override_result["isError"] is False

    # Remote: no store_root/actor_id/actor_roles - identity comes from AP_API_TOKEN.
    finalize_result = _call("package_finalize", {"package_dir": pkg_dir}, msg_id=4)
    assert finalize_result["isError"] is False, finalize_result
    finalize_payload = _payload(finalize_result)
    assert finalize_payload["status"] == "draft"
    package_id = finalize_payload["package_id"]
    package_version = finalize_payload["package_version"]

    # Prove it actually reached the real store behind the HTTP API, not a mock.
    record = store.get(package_id, package_version)
    assert record is not None
    assert record.status == "draft"
    assert record.published_by_id == "tom.planner"

    submit_result = _call(
        "package_submit_review",
        {"package_id": package_id, "package_version": package_version},
        msg_id=5,
    )
    assert submit_result["isError"] is False, submit_result
    submit_payload = _payload(submit_result)
    assert submit_payload["status"] == "in_review"

    record = store.get(package_id, package_version)
    assert record.status == "in_review"
    page = store.list()
    assert any(r.package_id == package_id and r.status == "in_review" for r in page.items)


def test_remote_mode_finalize_missing_local_fields_is_fine_not_required(remote_api, tmp_path):
    """store_root/actor_id/actor_roles are schema-optional precisely so remote mode doesn't need
    them - confirm omitting them in remote mode is not itself a validation error."""
    pkg_dir = str(tmp_path / "pkg")
    _call("package_create", {"dest_dir": pkg_dir, "title": "Remote pack", "analyst_id": "tom.planner"}, msg_id=1)

    finalize_result = _call("package_finalize", {"package_dir": pkg_dir}, msg_id=2)
    assert finalize_result["isError"] is False, finalize_result


def test_remote_mode_policy_rejection_is_planner_serving_not_a_stack_trace(remote_api, tmp_path):
    """A remote-side policy rejection (here: submitting a package_version that was never
    published) must surface through the same ToolValidationError shape local mode uses."""
    submit_result = _call(
        "package_submit_review",
        {"package_id": "does-not-exist", "package_version": "1"},
        msg_id=1,
    )
    assert submit_result["isError"] is True
    text = submit_result["content"][0]["text"]
    assert "Traceback" not in text


def test_local_mode_unaffected_when_remote_env_vars_are_unset(tmp_path):
    """Sanity check that local mode (the default, no AP_API_URL/AP_API_TOKEN) is untouched by this
    task's changes - package_finalize/package_submit_review still work end to end against a local
    store, same as tests/test_mcp_e2e_authoring_loop.py."""
    pkg_dir = str(tmp_path / "pkg")
    store_root = str(tmp_path / "store")

    _call("package_create", {"dest_dir": pkg_dir, "title": "Local pack", "analyst_id": "tom.analyst"}, msg_id=1)
    finalize_result = _call(
        "package_finalize",
        {"package_dir": pkg_dir, "store_root": store_root, "actor_id": "tom.analyst", "actor_roles": "analyst"},
        msg_id=2,
    )
    assert finalize_result["isError"] is False
    payload = _payload(finalize_result)

    submit_result = _call(
        "package_submit_review",
        {
            "package_id": payload["package_id"],
            "package_version": payload["package_version"],
            "store_root": store_root,
            "actor_id": "tom.analyst",
            "actor_roles": "analyst",
        },
        msg_id=3,
    )
    assert submit_result["isError"] is False
    assert _payload(submit_result)["status"] == "in_review"


def test_local_mode_missing_store_root_is_rejected_with_planner_serving_message(tmp_path):
    pkg_dir = str(tmp_path / "pkg")
    _call("package_create", {"dest_dir": pkg_dir, "title": "Local pack", "analyst_id": "tom.analyst"}, msg_id=1)

    finalize_result = _call("package_finalize", {"package_dir": pkg_dir}, msg_id=2)
    assert finalize_result["isError"] is True
    text = finalize_result["content"][0]["text"]
    assert "store_root" in text
    assert "required in local mode" in text
