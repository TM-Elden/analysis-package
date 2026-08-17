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
from ap_proposals.policy import ProposalPolicy
from ap_proposals.store import ProposalStore
from ap_proposals.workflow import ProposalWorkflow
from ap_store.store import PackageStore

from _planner_bot_corpus import build_drift_corpus_with_index
from _planner_bot_fake_llm import RaisingOnceLLMClient, ScriptedDraftingLLMClient


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
    # This suite exercises the console decision flow (roles, CSRF, flash rendering) - not the C7
    # apply mechanism (see test_proposal_apply.py for that) - so it disables the
    # dry-run-required knob to keep a plain approve a one-call affair. The registry write itself
    # (apply_declarative) still runs for real, against this tmp_path store_root.
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


def test_sweep_button_discards_a_single_llm_error_and_continues_no_500(client_and_store, tmp_path):
    """D1 regression, end to end through the real route: a raising fake client on one finding out
    of a multi-finding drift corpus must not 500 the sweep button - the per-finding guard in
    `ap_planner_bot.service` discards just that finding (a counted, visible `llm_error` reason)
    and the rest of the sweep still runs, exactly as the console's other flash/notice patterns
    expect."""
    client, proposal_store, _auth = client_and_store
    package_store, index_store = build_drift_corpus_with_index(tmp_path)
    app.dependency_overrides[deps.get_store] = lambda: package_store
    app.dependency_overrides[deps.get_index] = lambda: index_store
    app.dependency_overrides[deps.get_llm_client] = lambda: RaisingOnceLLMClient(fail_on_call=1)
    csrf = _login(client, "cap.tan", "pw-cap")

    r = client.post("/console/standard/sweep", data={"status": "pending_hitl"}, headers={"X-Csrf": csrf})
    assert r.status_code == 200
    assert "llm_error" in r.text
    package_store.close()
    index_store.close()


def test_sweep_button_renders_inline_flash_not_a_raw_500_when_run_sweep_itself_raises(client_and_store, monkeypatch):
    """D1 route-level defense-in-depth: `standard_sweep`'s own try/except around `run_sweep` must
    turn *any* `LLMClientError` that reaches the route - not just the per-finding case the service
    layer already guards - into an inline `.flash` error, never a raw 500 (htmx's default swap
    silently ignores non-2xx, which is exactly the failure mode D1 reported). Monkeypatches
    `ap_console.routes.run_sweep` directly so this test exercises the route's own guard rather than
    re-testing the service-layer guard covered above and in test_planner_bot_service.py."""
    import ap_console.routes as routes_module
    from ap_manager_bot.llm_client import LLMClientError

    client, _proposal_store, _auth = client_and_store

    def _raising_run_sweep(*args, **kwargs):
        raise LLMClientError("simulated transport failure (429)")

    monkeypatch.setattr(routes_module, "run_sweep", _raising_run_sweep)
    csrf = _login(client, "cap.tan", "pw-cap")

    r = client.post("/console/standard/sweep", data={"status": "pending_hitl"}, headers={"X-Csrf": csrf})
    assert r.status_code == 200
    assert 'class="flash"' in r.text


def test_proposal_detail_renders_diff_evidence_and_no_dry_run_recorded_yet(client_and_store):
    client, store, _auth = client_and_store
    record = _create_proposal(store)
    _login(client, "cap.tan", "pw-cap")

    r = client.get(f"/console/standard/proposals/{record.proposal_id}")
    assert r.status_code == 200
    assert "SUPPLIER_CHANGE" in r.text  # after-diff content
    assert "pkg-1" in r.text and "pkg-2" in r.text  # evidence links
    assert "no dry-run recorded yet" in r.text.lower()


def test_proposal_detail_missing_proposal_is_404(client_and_store):
    client, _store, _auth = client_and_store
    _login(client, "cap.tan", "pw-cap")
    r = client.get("/console/standard/proposals/prop_does_not_exist")
    assert r.status_code == 404


def test_dry_run_button_actually_records_a_real_dry_run(client_and_store):
    """D4: the console button now calls `ProposalWorkflow.record_dry_run` for real (previously it
    only ever echoed a pre-existing `dry_run_json`, which nothing in the console ever populated).
    Verified against the store, not just the rendered panel text."""
    client, store, _auth = client_and_store
    record = _create_proposal(store)
    assert record.dry_run() is None
    csrf = _login(client, "cap.tan", "pw-cap")

    r = client.post(f"/console/standard/proposals/{record.proposal_id}/dry-run", headers={"X-Csrf": csrf})
    assert r.status_code == 200
    assert "no dry-run recorded yet" not in r.text.lower()

    updated = store.get(record.proposal_id)
    assert updated.dry_run() is not None


def test_dry_run_wiring_unblocks_an_approve_that_previously_flashed_no_recorded_dry_run(client_and_store):
    """D4 acceptance: with `require_dry_run_for_declarative` on (the real default, unlike this
    file's other tests which disable it to isolate decision-flow behavior), approving a
    declarative proposal must fail until the dry-run is recorded, then succeed once the console's
    "Run dry-run" button has actually run one."""
    client, store, _auth = client_and_store
    record = _create_proposal(store)
    app.dependency_overrides[deps.get_proposal_workflow] = lambda: ProposalWorkflow(store=store)
    csrf = _login(client, "cap.tan", "pw-cap")

    blocked = client.post(
        f"/console/standard/proposals/{record.proposal_id}/decision",
        data={"to_status": "approved"},
        headers={"X-Csrf": csrf},
    )
    assert blocked.status_code == 200
    assert "dry-run" in blocked.text.lower()
    assert store.get(record.proposal_id).status == "pending_hitl"

    dry_run_resp = client.post(f"/console/standard/proposals/{record.proposal_id}/dry-run", headers={"X-Csrf": csrf})
    assert dry_run_resp.status_code == 200
    assert store.get(record.proposal_id).dry_run() is not None

    approved = client.post(
        f"/console/standard/proposals/{record.proposal_id}/decision",
        data={"to_status": "approved"},
        headers={"X-Csrf": csrf},
    )
    assert approved.status_code == 200
    assert store.get(record.proposal_id).status == "approved"


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
