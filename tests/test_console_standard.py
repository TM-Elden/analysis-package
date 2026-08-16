"""Manager console "Standard" tab (P4 first cut): proposal queue, detail page, decision flow
(approve / approve-with-edits / reject), sweep-button and dry-run-panel honesty, and the interim
changelog view. `base_url="https://testserver"` is required for the same reason test_console.py
needs it: `POST /login` sets a `Secure` cookie.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import ap_api.deps as deps
from ap_api.app import app
from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_auth.store import AuthStore
from ap_index.index_store import IndexStore
from ap_proposals.store import ProposalStore
from ap_proposals.workflow import ProposalWorkflow
from ap_store.store import PackageStore

from _planner_bot_corpus import build_drift_corpus_with_index
from _planner_bot_fake_llm import ScriptedDraftingLLMClient


@pytest.fixture()
def client_and_store(tmp_path):
    proposal_store = ProposalStore(tmp_path / "store")
    package_store = PackageStore(tmp_path / "store")
    index_store = IndexStore(tmp_path / "index")
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    app.dependency_overrides[deps.get_proposal_store] = lambda: proposal_store
    app.dependency_overrides[deps.get_store] = lambda: package_store
    app.dependency_overrides[deps.get_index] = lambda: index_store
    app.dependency_overrides[deps.get_auth_store] = lambda: auth_store
    # No real ANTHROPIC_API_KEY in tests - the sweep button's llm_client dependency is overridden
    # with the same harness-exercising fake test_planner_bot_service.py uses, not a real API call.
    app.dependency_overrides[deps.get_llm_client] = lambda: ScriptedDraftingLLMClient()

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
        index_store.close()
        auth_store.close()


def _login(client: TestClient, user_id: str, password: str) -> str:
    r = client.post("/login", json={"user_id": user_id, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]


def _diff(code: str = "SUPPLIER_CHANGE") -> dict:
    return {"profile": "commodity", "file": "reason_codes.json", "before": None, "after": {"codes": [code]}}


def _create_proposal(store: ProposalStore, *, kind: str = "profile_change", diff: dict | None = None):
    wf = ProposalWorkflow(store=store)
    return wf.create(
        kind=kind,
        summary="Add SUPPLIER_CHANGE reason code",
        rationale="Seen 12 times in the last 30 days of override evidence",
        diff=diff if diff is not None else _diff(),
        evidence={"package_ids": ["pkg-1", "pkg-2"]},
        actor=Identity(id="sweep.bot", roles=frozenset({Role.ANALYST})),
    )


def test_logged_out_standard_pages_redirect_to_login(client_and_store):
    client, store, _auth = client_and_store
    record = _create_proposal(store)
    for path in ("/console/standard", f"/console/standard/proposals/{record.proposal_id}", "/console/standard/changelog"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].startswith("/console/login")


def test_nav_includes_standard_tab(client_and_store):
    client, store, _auth = client_and_store
    _login(client, "cap.tan", "pw-cap")
    r = client.get("/console/packages")
    assert 'href="/console/standard"' in r.text


def test_standard_queue_lists_pending_proposal(client_and_store):
    client, store, _auth = client_and_store
    record = _create_proposal(store)
    _login(client, "cap.tan", "pw-cap")

    r = client.get("/console/standard")
    assert r.status_code == 200
    assert record.proposal_id in r.text
    assert record.summary in r.text
    assert "2 packages" in r.text  # evidence count from {"package_ids": ["pkg-1", "pkg-2"]}


def test_standard_queue_status_tab_filters_out_pending(client_and_store):
    client, store, _auth = client_and_store
    record = _create_proposal(store)
    _login(client, "cap.tan", "pw-cap")

    r = client.get("/console/standard/table?status=approved")
    assert r.status_code == 200
    assert record.proposal_id not in r.text
    assert "Nothing here" in r.text


def test_sweep_button_runs_the_real_scan_on_an_empty_store(client_and_store):
    """`fathm-p4-sweep`: the button now runs the real scan/detect/draft pipeline (previously a
    documented no-op) - against the default overridden (empty) package store/index, so it finds
    nothing and creates nothing, but the notice reflects a real run, not a "not wired up" stub."""
    client, store, _auth = client_and_store
    csrf = _login(client, "cap.tan", "pw-cap")

    r = client.post("/console/standard/sweep", data={"status": "pending_hitl"}, headers={"X-Csrf": csrf})
    assert r.status_code == 200
    assert "0 finding" in r.text.lower()
    assert "0 proposal" in r.text.lower()
    assert store.list().total == 0


def test_sweep_button_drafts_real_proposals_from_a_seeded_drift_corpus(client_and_store, tmp_path):
    client, proposal_store, _auth = client_and_store
    package_store, index_store = build_drift_corpus_with_index(tmp_path)
    app.dependency_overrides[deps.get_store] = lambda: package_store
    app.dependency_overrides[deps.get_index] = lambda: index_store
    csrf = _login(client, "cap.tan", "pw-cap")

    r = client.post("/console/standard/sweep", data={"status": "pending_hitl"}, headers={"X-Csrf": csrf})
    assert r.status_code == 200
    assert proposal_store.list().total > 0
    assert "proposal(s) created" in r.text
    package_store.close()
    index_store.close()


def test_proposal_detail_renders_diff_evidence_and_dry_run_not_available(client_and_store):
    client, store, _auth = client_and_store
    record = _create_proposal(store)
    _login(client, "cap.tan", "pw-cap")

    r = client.get(f"/console/standard/proposals/{record.proposal_id}")
    assert r.status_code == 200
    assert "SUPPLIER_CHANGE" in r.text  # after-diff content
    assert "pkg-1" in r.text and "pkg-2" in r.text  # evidence links
    assert "not yet available" in r.text.lower()  # dry-run panel is honest about the stub


def test_proposal_detail_missing_proposal_is_404(client_and_store):
    client, _store, _auth = client_and_store
    _login(client, "cap.tan", "pw-cap")
    r = client.get("/console/standard/proposals/prop_does_not_exist")
    assert r.status_code == 404


def test_dry_run_button_shows_not_available_state_not_a_fake_result(client_and_store):
    client, store, _auth = client_and_store
    record = _create_proposal(store)
    csrf = _login(client, "cap.tan", "pw-cap")

    r = client.post(f"/console/standard/proposals/{record.proposal_id}/dry-run", headers={"X-Csrf": csrf})
    assert r.status_code == 200
    assert "not yet available" in r.text.lower()
    assert "fathm-p4-registry-dryrun" in r.text


def test_approve_decision_changes_real_store_status(client_and_store):
    client, store, _auth = client_and_store
    record = _create_proposal(store)
    csrf = _login(client, "cap.tan", "pw-cap")

    r = client.post(
        f"/console/standard/proposals/{record.proposal_id}/decision",
        data={"to_status": "approved"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200
    updated = store.get(record.proposal_id)
    assert updated.status == "approved"
    assert updated.decided_by_id == "cap.tan"
    assert updated.edited_diff() is None


def test_approve_with_edits_stores_edited_diff_beside_original(client_and_store):
    client, store, _auth = client_and_store
    record = _create_proposal(store)
    csrf = _login(client, "cap.tan", "pw-cap")

    edited = _diff("SUPPLIER_CHANGE_V2")
    r = client.post(
        f"/console/standard/proposals/{record.proposal_id}/decision",
        data={"to_status": "approved", "edited_diff": __import__("json").dumps(edited)},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200
    updated = store.get(record.proposal_id)
    assert updated.status == "approved"
    assert updated.edited_diff() == edited
    assert updated.diff() == _diff()  # original diff untouched


def test_reject_requires_reason_enforced_server_side(client_and_store):
    client, store, _auth = client_and_store
    record = _create_proposal(store)
    csrf = _login(client, "cap.tan", "pw-cap")

    r = client.post(
        f"/console/standard/proposals/{record.proposal_id}/decision",
        data={"to_status": "rejected"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200
    assert "flash" in r.text
    assert "reason" in r.text.lower()
    assert store.get(record.proposal_id).status == "pending_hitl"


def test_decision_error_banner_is_not_duplicated_into_dry_run_panel(client_and_store):
    """The decision route re-renders `_proposal_detail_body.html`, which `{% include %}`s
    `_dry_run_panel.html` with shared Jinja context. Both partials used to guard their flash div on
    the same `error` variable, so a decision error (e.g. reject-without-reason) rendered twice - once
    as the real decision-error banner, once leaking into the unrelated dry-run panel. The dry-run
    panel's own error state is keyed off a distinct `dry_run_error` var it never receives here."""
    client, store, _auth = client_and_store
    record = _create_proposal(store)
    csrf = _login(client, "cap.tan", "pw-cap")

    r = client.post(
        f"/console/standard/proposals/{record.proposal_id}/decision",
        data={"to_status": "rejected"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200
    assert r.text.count('class="flash"') == 1


def test_reject_with_reason_changes_real_store_status(client_and_store):
    client, store, _auth = client_and_store
    record = _create_proposal(store)
    csrf = _login(client, "cap.tan", "pw-cap")

    r = client.post(
        f"/console/standard/proposals/{record.proposal_id}/decision",
        data={"to_status": "rejected", "reason": "not enough evidence"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200
    updated = store.get(record.proposal_id)
    assert updated.status == "rejected"
    assert updated.decision_reason == "not enough evidence"


def test_non_approver_decision_blocked_with_clear_message_not_500(client_and_store):
    client, store, _auth = client_and_store
    record = _create_proposal(store)
    csrf = _login(client, "ro.reader", "pw-ro")  # team_reader, no standard_approver role

    r = client.post(
        f"/console/standard/proposals/{record.proposal_id}/decision",
        data={"to_status": "approved"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200  # never a raw 500/403
    assert "flash" in r.text
    assert "standard_approver" in r.text.lower()
    assert store.get(record.proposal_id).status == "pending_hitl"


def test_creator_without_approver_role_cannot_self_decide(client_and_store):
    """The proposal's own creator (sweep.bot, analyst-only) attempting to decide it: same
    role-enforcement path as any other non-approver, matching the review queue's self-review
    test pattern - a decision-maker without the right role never gets to decide, self or not."""
    client, store, auth_store = client_and_store
    record = _create_proposal(store)
    auth_store.create_user(
        "sweep.bot.login", display_name="Sweep login", roles=frozenset({Role.ANALYST}), password="pw-sweep2"
    )
    csrf = _login(client, "sweep.bot.login", "pw-sweep2")

    r = client.post(
        f"/console/standard/proposals/{record.proposal_id}/decision",
        data={"to_status": "approved"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200
    assert "flash" in r.text
    assert store.get(record.proposal_id).status == "pending_hitl"


def test_changelog_lists_decided_proposals_and_excludes_pending(client_and_store):
    client, store, _auth = client_and_store
    pending = _create_proposal(store)
    decided = _create_proposal(store, diff=_diff("OTHER_CODE"))
    csrf = _login(client, "cap.tan", "pw-cap")
    client.post(
        f"/console/standard/proposals/{decided.proposal_id}/decision",
        data={"to_status": "approved"},
        headers={"X-Csrf": csrf},
    )

    r = client.get("/console/standard/changelog")
    assert r.status_code == 200
    assert decided.proposal_id in r.text
    assert pending.proposal_id not in r.text
