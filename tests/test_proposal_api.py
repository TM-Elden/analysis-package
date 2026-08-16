"""C6/C7 proposal API: GET /proposals, POST /proposals, POST /proposals/{id}/decision."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import ap_api.deps as deps
from ap_api.app import app
from ap_auth.roles import Role
from ap_auth.store import AuthStore
from ap_proposals.policy import ProposalPolicy
from ap_proposals.store import ProposalStore
from ap_proposals.workflow import ProposalWorkflow
from ap_store.store import PackageStore


@pytest.fixture()
def client_and_store(tmp_path):
    proposal_store = ProposalStore(tmp_path / "store")
    package_store = PackageStore(tmp_path / "store")
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    app.dependency_overrides[deps.get_proposal_store] = lambda: proposal_store
    app.dependency_overrides[deps.get_store] = lambda: package_store
    app.dependency_overrides[deps.get_auth_store] = lambda: auth_store
    # These tests exercise the API contract (auth, roles, CSRF, request/response shapes), not the
    # apply mechanism (see test_proposal_apply.py for that) - disable the dry-run-required knob so
    # a plain approve stays a one-call affair. The registry write itself (apply_declarative) still
    # runs for real, against this tmp_path store_root.
    app.dependency_overrides[deps.get_proposal_workflow] = lambda: ProposalWorkflow(
        store=proposal_store, policy=ProposalPolicy(require_dry_run_for_declarative=False)
    )

    auth_store.create_user("sweep.bot", display_name="Sweep", roles=frozenset({Role.ANALYST}), password="pw-sweep")
    auth_store.create_user(
        "cap.tan", display_name="Captain", roles=frozenset({Role.STANDARD_APPROVER}), password="pw-cap"
    )
    auth_store.create_user("ro.reader", display_name="Reader", roles=frozenset({Role.TEAM_READER}), password="pw-ro")

    client = TestClient(app, base_url="https://testserver")
    try:
        yield client, proposal_store, auth_store
    finally:
        app.dependency_overrides.clear()
        proposal_store.close()
        package_store.close()
        auth_store.close()


def _login(client: TestClient, user_id: str, password: str) -> dict:
    r = client.post("/login", json={"user_id": user_id, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _csrf_headers(login_body: dict) -> dict:
    return {"X-Csrf": login_body["csrf_token"]}


def _diff() -> dict:
    return {"profile": "commodity", "file": "reason_codes.json", "before": None, "after": {"codes": ["X"]}}


def test_no_session_no_bearer_is_401(client_and_store):
    client, *_ = client_and_store
    r = client.get("/proposals")
    assert r.status_code == 401


def test_create_requires_no_special_role_just_auth(client_and_store):
    client, *_ = client_and_store
    body = _login(client, "ro.reader", "pw-ro")
    r = client.post(
        "/proposals",
        json={"kind": "profile_change", "summary": "s", "rationale": "r", "diff": _diff(), "evidence": {}},
        headers=_csrf_headers(body),
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending_hitl"


def test_create_rejects_malformed_diff(client_and_store):
    client, *_ = client_and_store
    body = _login(client, "sweep.bot", "pw-sweep")
    r = client.post(
        "/proposals",
        json={"kind": "profile_change", "summary": "s", "rationale": "r", "diff": {"profile": "x"}, "evidence": {}},
        headers=_csrf_headers(body),
    )
    assert r.status_code == 400


def test_full_flow_create_list_approve(client_and_store):
    client, *_ = client_and_store
    creator = _login(client, "sweep.bot", "pw-sweep")
    r = client.post(
        "/proposals",
        json={"kind": "profile_change", "summary": "s", "rationale": "r", "diff": _diff(), "evidence": {"a": 1}},
        headers=_csrf_headers(creator),
    )
    assert r.status_code == 201, r.text
    proposal_id = r.json()["proposal_id"]

    r = client.get("/proposals", params={"status": "pending_hitl"})
    assert r.status_code == 200
    assert any(item["proposal_id"] == proposal_id for item in r.json()["items"])

    approver = _login(client, "cap.tan", "pw-cap")
    r = client.post(
        f"/proposals/{proposal_id}/decision",
        json={"to_status": "approved"},
        headers=_csrf_headers(approver),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert r.json()["decided_by_id"] == "cap.tan"


def test_non_approver_decision_is_403(client_and_store):
    client, *_ = client_and_store
    creator = _login(client, "sweep.bot", "pw-sweep")
    r = client.post(
        "/proposals",
        json={"kind": "profile_change", "summary": "s", "rationale": "r", "diff": _diff(), "evidence": {}},
        headers=_csrf_headers(creator),
    )
    proposal_id = r.json()["proposal_id"]

    reader = _login(client, "ro.reader", "pw-ro")
    r = client.post(
        f"/proposals/{proposal_id}/decision",
        json={"to_status": "approved"},
        headers=_csrf_headers(reader),
    )
    assert r.status_code == 403


def test_reject_without_reason_is_403(client_and_store):
    client, *_ = client_and_store
    creator = _login(client, "sweep.bot", "pw-sweep")
    r = client.post(
        "/proposals",
        json={"kind": "profile_change", "summary": "s", "rationale": "r", "diff": _diff(), "evidence": {}},
        headers=_csrf_headers(creator),
    )
    proposal_id = r.json()["proposal_id"]

    approver = _login(client, "cap.tan", "pw-cap")
    r = client.post(
        f"/proposals/{proposal_id}/decision",
        json={"to_status": "rejected"},
        headers=_csrf_headers(approver),
    )
    assert r.status_code == 403


def test_decision_state_changing_request_without_csrf_is_403(client_and_store):
    client, *_ = client_and_store
    creator = _login(client, "sweep.bot", "pw-sweep")
    r = client.post(
        "/proposals",
        json={"kind": "profile_change", "summary": "s", "rationale": "r", "diff": _diff(), "evidence": {}},
        headers=_csrf_headers(creator),
    )
    proposal_id = r.json()["proposal_id"]

    _login(client, "cap.tan", "pw-cap")
    r = client.post(f"/proposals/{proposal_id}/decision", json={"to_status": "approved"})
    assert r.status_code == 403


def test_unknown_proposal_decision_is_404(client_and_store):
    client, *_ = client_and_store
    approver = _login(client, "cap.tan", "pw-cap")
    r = client.post(
        "/proposals/prop_doesnotexist/decision",
        json={"to_status": "approved"},
        headers=_csrf_headers(approver),
    )
    assert r.status_code == 404
