"""Manager console (P3.4): login redirect enforcement, filterable package list, package detail,
and the embedded gate report - rendered for at least the gold-pack example package (per the task's
acceptance bar). `base_url="https://testserver"` is required for the same reason test_api.py needs
it: `POST /login` sets a `Secure` cookie.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import ap_api.deps as deps
from ap_api.app import app
from ap_auth.roles import Role
from ap_auth.store import AuthStore
from ap_store.store import PackageStore
from conftest import EXAMPLE_PACKAGE


@pytest.fixture()
def client_and_store(tmp_path):
    store = PackageStore(tmp_path / "store")
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[deps.get_auth_store] = lambda: auth_store

    auth_store.create_user("tom.analyst", display_name="Tom", roles=frozenset({Role.ANALYST}), password="pw-tom")
    auth_store.create_user("jane.lead", display_name="Jane", roles=frozenset({Role.REVIEWER}), password="pw-jane")

    client = TestClient(app, base_url="https://testserver")
    try:
        yield client, store, auth_store
    finally:
        app.dependency_overrides.clear()
        store.close()
        auth_store.close()


def _login(client: TestClient) -> None:
    r = client.post("/login", json={"user_id": "tom.analyst", "password": "pw-tom"})
    assert r.status_code == 200, r.text


def _publish_example(store: PackageStore):
    from ap_auth.identity import Identity

    actor = Identity(id="tom.analyst", roles=frozenset({Role.ANALYST}))
    return store.publish(EXAMPLE_PACKAGE, actor=actor)


@pytest.mark.parametrize(
    "path",
    ["/console/packages", "/console/packages/commodity-commit-v1"],
)
def test_logged_out_console_page_redirects_to_login(client_and_store, path):
    client, _store, _auth = client_and_store
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/console/login")


def test_login_page_renders_without_auth(client_and_store):
    client, _store, _auth = client_and_store
    r = client.get("/console/login")
    assert r.status_code == 200
    assert "Log in" in r.text


def test_package_list_renders_published_package(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _login(client)

    r = client.get("/console/packages")
    assert r.status_code == 200
    assert record.package_id in r.text
    assert record.title in r.text
    assert "wordmark" in r.text  # brand wordmark present


def test_package_list_filter_partial_respects_status(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _login(client)

    r = client.get("/console/packages/table", params={"status": "draft"})
    assert r.status_code == 200
    assert record.package_id in r.text

    r = client.get("/console/packages/table", params={"status": "approved"})
    assert r.status_code == 200
    assert record.package_id not in r.text
    assert "No packages match" in r.text


def test_package_detail_renders_manifest_summary_and_owners(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _login(client)

    r = client.get(f"/console/packages/{record.package_id}")
    assert r.status_code == 200
    assert record.package_id in r.text
    assert record.title in r.text
    assert record.status in r.text
    assert (record.analyst_id or "") in r.text


def test_package_detail_missing_package_is_404(client_and_store):
    client, _store, _auth = client_and_store
    _login(client)
    r = client.get("/console/packages/does-not-exist")
    assert r.status_code == 404


def test_gate_report_embeds_real_check_results(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _login(client)

    r = client.get(f"/console/packages/{record.package_id}/gate-report", params={"version": record.package_version})
    assert r.status_code == 200
    assert "fathm L1 report" in r.text
    assert "PASS" in r.text or "FAIL" in r.text


def test_logout_link_target_revokes_session(client_and_store):
    client, store, auth_store = client_and_store
    _publish_example(store)
    body_r = client.post("/login", json={"user_id": "tom.analyst", "password": "pw-tom"})
    csrf = body_r.json()["csrf_token"]

    r = client.post("/logout", headers={"X-Csrf": csrf})
    assert r.status_code == 200

    r = client.get("/console/packages", follow_redirects=False)
    assert r.status_code == 303


# -- Review queue (P3.5) ---------------------------------------------------------------------


def _submit_for_review(store: PackageStore, record):
    """Bypasses the UI to drive draft -> in_review directly through the real workflow - the
    review queue's own job is approve/reject, not submission (out of this task's scope)."""
    from ap_auth.identity import Identity
    from ap_review.workflow import ReviewWorkflow

    wf = ReviewWorkflow(store=store)
    return wf.transition(
        record.package_id,
        record.package_version,
        to_status="in_review",
        actor=Identity(id="tom.analyst", roles=frozenset({Role.ANALYST})),
    )


def _login_reviewer(client: TestClient) -> str:
    r = client.post("/login", json={"user_id": "jane.lead", "password": "pw-jane"})
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]


def test_review_queue_lists_only_in_review_packages(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _submit_for_review(store, record)
    _login(client)

    r = client.get("/console/review-queue")
    assert r.status_code == 200
    assert record.package_id in r.text
    assert "Nothing waiting for review" not in r.text


def test_review_queue_excludes_draft_packages(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)  # stays draft, never submitted
    _login(client)

    r = client.get("/console/review-queue")
    assert r.status_code == 200
    assert record.package_id not in r.text
    assert "Nothing waiting for review" in r.text


def test_review_queue_approve_action_changes_real_store_status(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _submit_for_review(store, record)
    csrf = _login_reviewer(client)

    r = client.post(
        f"/console/packages/{record.package_id}/review",
        data={"package_version": record.package_version, "to_status": "approved"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200
    assert "Nothing waiting for review" in r.text  # dropped out of the queue on swap-in

    # Verify against the store directly (not just the UI claiming success).
    updated = store.get(record.package_id, record.package_version)
    assert updated.status == "approved"


def test_review_queue_reject_requires_reason_enforced_server_side(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _submit_for_review(store, record)
    csrf = _login_reviewer(client)

    r = client.post(
        f"/console/packages/{record.package_id}/review",
        data={"package_version": record.package_version, "to_status": "rejected"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200
    assert "flash" in r.text
    assert "reason" in r.text.lower()

    updated = store.get(record.package_id, record.package_version)
    assert updated.status == "in_review"  # unchanged - not silently rejected without a reason


def test_review_queue_reject_with_reason_changes_real_store_status(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _submit_for_review(store, record)
    csrf = _login_reviewer(client)

    r = client.post(
        f"/console/packages/{record.package_id}/review",
        data={"package_version": record.package_version, "to_status": "rejected", "reason": "missing evidence"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200

    updated = store.get(record.package_id, record.package_version)
    assert updated.status == "rejected"


def test_review_queue_self_review_blocked_with_clear_message_not_500(client_and_store):
    client, store, auth_store = client_and_store
    record = _publish_example(store)
    _submit_for_review(store, record)
    # record.analyst_id comes from EXAMPLE_PACKAGE's manifest owners.analyst.id ("planner.example"),
    # not the identity that called store.publish - log in as that same id, holding the reviewer
    # role too, to exercise the "reviewer is also the analyst of record" path.
    assert record.analyst_id == "planner.example"
    auth_store.create_user(
        "planner.example", display_name="Planner", roles=frozenset({Role.REVIEWER}), password="pw-planner"
    )
    csrf_r = client.post("/login", json={"user_id": "planner.example", "password": "pw-planner"})
    assert csrf_r.status_code == 200, csrf_r.text
    csrf = csrf_r.json()["csrf_token"]

    r = client.post(
        f"/console/packages/{record.package_id}/review",
        data={"package_version": record.package_version, "to_status": "approved"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200  # never a raw 500
    assert "flash" in r.text
    assert "self" in r.text.lower() or "distinct" in r.text.lower()

    updated = store.get(record.package_id, record.package_version)
    assert updated.status == "in_review"  # blocked, not silently approved


def test_review_queue_withdraw_by_non_owner_reviewer_blocked_with_clear_message_not_500(client_and_store):
    """D3 fix: jane.lead is a real reviewer but not this package's analyst - pulling it back to
    draft through the same console route the review queue uses must be rejected with a flash
    message, not a raw 500, and the store status must stay unchanged."""
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _submit_for_review(store, record)
    csrf = _login_reviewer(client)

    r = client.post(
        f"/console/packages/{record.package_id}/review",
        data={"package_version": record.package_version, "to_status": "draft"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200  # never a raw 500
    assert "flash" in r.text
    assert "withdraw/revise" in r.text.lower()

    updated = store.get(record.package_id, record.package_version)
    assert updated.status == "in_review"  # unchanged - not silently withdrawn


def test_package_detail_audit_trail_matches_full_history(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _submit_for_review(store, record)
    csrf = _login_reviewer(client)
    client.post(
        f"/console/packages/{record.package_id}/review",
        data={"package_version": record.package_version, "to_status": "approved"},
        headers={"X-Csrf": csrf},
    )

    r = client.get(f"/console/packages/{record.package_id}", params={"version": record.package_version})
    assert r.status_code == 200

    api_entries = store.audit_trail(record.package_id, record.package_version)
    assert len(api_entries) == 3  # publish -> in_review -> approved
    for entry in api_entries:
        assert entry.actor_id in r.text
        assert entry.to_status in r.text
