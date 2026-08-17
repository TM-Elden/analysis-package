"""NC.3 (`data/fathm-native-chat-readiness/report.md` §5.4 in the firstmate repo): inline
approve/reject affordances on the Ask tab's citations. This is a human-clicked UI layer over the
already-merged `POST /console/packages/{id}/review` route (P3.5) - the new surface here is
`GET /console/packages/{id}/review-actions` (the partial the Ask tab's citation rendering loads per
citation, see `base.html`) and `console_review_action`'s `source=chat` branch. Nothing here talks to
`ManagerBot`'s tool loop directly; `test_manager_bot_tool_schema_unchanged` is the regression proof
that this task added no action tool to it, per the brief's hard constraint.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import ap_api.deps as deps
from ap_api.app import app
from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_auth.store import AuthStore
from ap_review.workflow import ReviewWorkflow
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


def _login_reviewer(client: TestClient) -> str:
    r = client.post("/login", json={"user_id": "jane.lead", "password": "pw-jane"})
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]


def _publish_example(store: PackageStore):
    actor = Identity(id="tom.analyst", roles=frozenset({Role.ANALYST}))
    return store.publish(EXAMPLE_PACKAGE, actor=actor)


def _submit_for_review(store: PackageStore, record):
    wf = ReviewWorkflow(store=store)
    return wf.transition(
        record.package_id,
        record.package_version,
        to_status="in_review",
        actor=Identity(id="tom.analyst", roles=frozenset({Role.ANALYST})),
    )


# -- Rendering: buttons appear only for a live in_review status --------------------------------


def test_review_actions_partial_renders_buttons_for_in_review_package(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _submit_for_review(store, record)
    _login_reviewer(client)

    r = client.get(f"/console/packages/{record.package_id}/review-actions")
    assert r.status_code == 200
    assert "btn approve" in r.text
    assert "btn reject" in r.text
    assert f'value="{record.package_version}"' in r.text


@pytest.mark.parametrize("to_status", ["approved", "rejected"])
def test_review_actions_partial_renders_no_buttons_once_decided(client_and_store, to_status):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _submit_for_review(store, record)
    wf = ReviewWorkflow(store=store)
    wf.transition(
        record.package_id,
        record.package_version,
        to_status=to_status,
        actor=Identity(id="jane.lead", roles=frozenset({Role.REVIEWER})),
        reason="not needed" if to_status == "rejected" else None,
    )
    _login_reviewer(client)

    r = client.get(f"/console/packages/{record.package_id}/review-actions")
    assert r.status_code == 200
    assert "btn approve" not in r.text
    assert "btn reject" not in r.text


def test_review_actions_partial_renders_no_buttons_for_draft_package(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)  # stays draft, never submitted
    _login_reviewer(client)

    r = client.get(f"/console/packages/{record.package_id}/review-actions")
    assert r.status_code == 200
    assert "btn approve" not in r.text
    assert "btn reject" not in r.text


def test_review_actions_partial_uses_the_live_status_not_a_stale_version(client_and_store, tmp_path):
    """A citation can point at an older, already-approved version's chunk while the package_id's
    CURRENT (latest-published) version has since moved to in_review - the partial must key off the
    live status, not whatever the cited chunk happened to snapshot."""
    import yaml
    from ap_agent_tools.tools import package_create

    client, store, _auth = client_and_store
    pkg_dir = package_create(tmp_path / "pkg", title="Versioned pack", analyst_id="tom.analyst")
    actor = Identity(id="tom.analyst", roles=frozenset({Role.ANALYST}))
    record_v1 = store.publish(pkg_dir, actor=actor)
    _submit_for_review(store, record_v1)
    csrf = _login_reviewer(client)
    approve = client.post(
        f"/console/packages/{record_v1.package_id}/review",
        data={"package_version": record_v1.package_version, "to_status": "approved"},
        headers={"X-Csrf": csrf},
    )
    assert approve.status_code == 200
    assert store.get(record_v1.package_id, record_v1.package_version).status == "approved"

    manifest_path = pkg_dir / "MANIFEST.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["package_version"] = "1.0.1"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    record_v2 = store.publish(pkg_dir, actor=actor)
    _submit_for_review(store, record_v2)

    r = client.get(f"/console/packages/{record_v1.package_id}/review-actions")
    assert r.status_code == 200
    assert "btn approve" in r.text
    assert f'value="{record_v2.package_version}"' in r.text  # acts on the live version, not v1


# -- Approving/rejecting from the Ask-tab affordance actually transitions the package ------------


def test_chat_source_approve_transitions_the_real_store_status(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _submit_for_review(store, record)
    csrf = _login_reviewer(client)

    r = client.post(
        f"/console/packages/{record.package_id}/review",
        data={"package_version": record.package_version, "to_status": "approved", "source": "chat"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200
    assert "btn approve" not in r.text  # buttons dropped from the re-rendered fragment

    updated = store.get(record.package_id, record.package_version)
    assert updated.status == "approved"


def test_chat_source_reject_requires_reason_enforced_server_side(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _submit_for_review(store, record)
    csrf = _login_reviewer(client)

    r = client.post(
        f"/console/packages/{record.package_id}/review",
        data={"package_version": record.package_version, "to_status": "rejected", "source": "chat"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200
    assert "flash" in r.text
    assert "reason" in r.text.lower()

    updated = store.get(record.package_id, record.package_version)
    assert updated.status == "in_review"  # unchanged - policy enforced exactly as the queue does


def test_chat_source_self_review_blocked_same_as_queue(client_and_store):
    client, store, auth_store = client_and_store
    record = _publish_example(store)
    _submit_for_review(store, record)
    assert record.analyst_id == "planner.example"
    auth_store.create_user(
        "planner.example", display_name="Planner", roles=frozenset({Role.REVIEWER}), password="pw-planner"
    )
    csrf_r = client.post("/login", json={"user_id": "planner.example", "password": "pw-planner"})
    assert csrf_r.status_code == 200, csrf_r.text
    csrf = csrf_r.json()["csrf_token"]

    r = client.post(
        f"/console/packages/{record.package_id}/review",
        data={"package_version": record.package_version, "to_status": "approved", "source": "chat"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200  # never a raw 500
    assert "flash" in r.text
    assert "self" in r.text.lower() or "distinct" in r.text.lower()

    updated = store.get(record.package_id, record.package_version)
    assert updated.status == "in_review"  # blocked, not silently approved


def test_chat_source_requires_csrf_same_as_queue(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _submit_for_review(store, record)
    _login_reviewer(client)  # logs in, establishing the session cookie, but discards the token

    r = client.post(
        f"/console/packages/{record.package_id}/review",
        data={"package_version": record.package_version, "to_status": "approved", "source": "chat"},
    )
    assert r.status_code == 200
    assert "flash" in r.text

    updated = store.get(record.package_id, record.package_version)
    assert updated.status == "in_review"


# -- Base template wiring: the Ask tab actually inserts the per-citation slot --------------------


def test_ask_tab_citation_handler_wires_the_review_actions_slot():
    base_html = (
        __import__("pathlib").Path(__file__).resolve().parents[1] / "src" / "ap_console" / "templates" / "base.html"
    ).read_text()
    assert "review-actions" in base_html
    assert "htmx.process" in base_html


# -- Hard constraint: ManagerBot gains no new tool ------------------------------------------------


def test_manager_bot_tool_schema_unchanged():
    """Regression guard for the brief's hard constraint: this task must not give ManagerBot a
    state-changing tool. Snapshots the exact tool-name set and confirms none of them look like an
    action/mutation (approve/reject/review/transition) - the four tools are unchanged from before
    this task (search_packages, get_package_summary, get_gate_report, provide_answer)."""
    from ap_manager_bot.tool_backend import TOOL_SCHEMAS

    assert set(TOOL_SCHEMAS.keys()) == {
        "search_packages",
        "get_package_summary",
        "get_gate_report",
        "provide_answer",
    }
    for name in TOOL_SCHEMAS:
        lowered = name.lower()
        assert not any(verb in lowered for verb in ("approve", "reject", "review", "transition", "decide"))
