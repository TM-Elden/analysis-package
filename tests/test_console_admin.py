"""Admin tab (P5.3): role gating (403 matrix), users & access (create/roles/password/disable/
tokens/sessions, last-admin guard, auth_audit), index health (C14 visibility), and settings
(retention_days + effective-config panel). `base_url="https://testserver"` is required for the
same reason test_console.py needs it: `POST /login` sets a `Secure` cookie.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

import ap_api.deps as deps
from ap_api.app import app
from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_auth.store import AuthStore
from ap_chat.identity_map import read_entries
from ap_gate.load_manifest import load_manifest
from ap_index.index_store import IndexStore
from ap_index.reindex import reindex_package
from ap_review.policy import ReviewPolicy
from ap_review.workflow import ReviewWorkflow
from ap_store.store import PackageStore

from conftest import EXAMPLE_PACKAGE


@pytest.fixture()
def client_and_store(tmp_path, monkeypatch):
    store = PackageStore(tmp_path / "store")
    index = IndexStore(tmp_path / "index")
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[deps.get_index] = lambda: index
    app.dependency_overrides[deps.get_auth_store] = lambda: auth_store
    # P5.4 team-bot provisioning writes here - a per-test tmp_path keeps the file isolated and,
    # since it doesn't exist until the first provision, exercises the "file doesn't exist yet"
    # path `read_entries`/`add_entry` are built to tolerate.
    allowlist_path = tmp_path / "chat_telegram_allowlist.json"
    monkeypatch.setenv("AP_CHAT_ALLOWLIST_PATH", str(allowlist_path))

    auth_store.create_user("root.admin", display_name="Root", roles=frozenset({Role.ADMIN}), password="pw-admin")
    auth_store.create_user("tom.analyst", display_name="Tom", roles=frozenset({Role.ANALYST}), password="pw-tom")

    client = TestClient(app, base_url="https://testserver")
    try:
        yield client, store, index, auth_store
    finally:
        app.dependency_overrides.clear()
        store.close()
        index.close()
        auth_store.close()


def _login(client: TestClient, user_id: str, password: str) -> str:
    r = client.post("/login", json={"user_id": user_id, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]


# -- role gating: every /console/admin* route 403s a non-admin identity -------------------------

_ADMIN_GET_PATHS = [
    "/console/admin/users",
    "/console/admin/team-bot",
    "/console/admin/index-health",
    "/console/admin/settings",
]


@pytest.mark.parametrize("path", _ADMIN_GET_PATHS)
def test_admin_routes_403_for_non_admin_identity(client_and_store, path):
    client, _store, _index, auth_store = client_and_store
    _login(client, "tom.analyst", "pw-tom")
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 403


def test_admin_root_403s_for_non_admin_identity(client_and_store):
    """`/console/admin` (no trailing slash) 307-redirects to `/console/admin/` before the
    `require_console_admin` dependency ever runs - follow the redirect and check the final status."""
    client, _store, _index, _auth = client_and_store
    _login(client, "tom.analyst", "pw-tom")
    r = client.get("/console/admin", follow_redirects=True)
    assert r.status_code == 403


def test_admin_user_detail_403s_for_non_admin_identity(client_and_store):
    client, _store, _index, _auth = client_and_store
    _login(client, "tom.analyst", "pw-tom")
    r = client.get("/console/admin/users/tom.analyst")
    assert r.status_code == 403


def test_admin_post_routes_403_for_non_admin_identity(client_and_store):
    client, _store, _index, _auth = client_and_store
    csrf = _login(client, "tom.analyst", "pw-tom")
    r = client.post(
        "/console/admin/users/tom.analyst/roles", data={"roles": "admin"}, headers={"X-Csrf": csrf}
    )
    assert r.status_code == 403


def test_admin_routes_redirect_to_login_when_logged_out(client_and_store):
    client, _store, _index, _auth = client_and_store
    r = client.get("/console/admin/users", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/console/login")


def test_admin_route_accessible_to_admin_identity(client_and_store):
    client, _store, _index, _auth = client_and_store
    _login(client, "root.admin", "pw-admin")
    r = client.get("/console/admin/users")
    assert r.status_code == 200
    assert "root.admin" in r.text


def test_admin_nav_item_hidden_for_non_admin(client_and_store):
    client, _store, _index, _auth = client_and_store
    _login(client, "tom.analyst", "pw-tom")
    r = client.get("/console/packages")
    assert r.status_code == 200
    assert 'href="/console/admin"' not in r.text


def test_admin_nav_item_shown_for_admin(client_and_store):
    client, _store, _index, _auth = client_and_store
    _login(client, "root.admin", "pw-admin")
    r = client.get("/console/packages")
    assert r.status_code == 200
    assert 'href="/console/admin"' in r.text


# -- users & access -----------------------------------------------------------------------------


def test_create_user_via_console(client_and_store):
    client, _store, _index, auth_store = client_and_store
    csrf = _login(client, "root.admin", "pw-admin")

    r = client.post(
        "/console/admin/users",
        data={"user_id": "new.hire", "display_name": "New Hire", "roles": ["analyst"], "password": "pw-new"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200
    assert "new.hire" in r.text
    assert auth_store.get_user("new.hire") is not None


def test_role_edit_changes_what_the_user_can_actually_do(client_and_store):
    """Real test per the acceptance criterion: after an admin edits roles via the console, the
    target user's own live session actually gains/loses access - not just a changed DB row."""
    client, _store, _index, auth_store = client_and_store
    admin_csrf = _login(client, "root.admin", "pw-admin")

    # tom starts analyst-only - admin routes 403 for him.
    tom_client = TestClient(app, base_url="https://testserver")
    _login(tom_client, "tom.analyst", "pw-tom")
    r = tom_client.get("/console/admin/users", follow_redirects=False)
    assert r.status_code == 403

    r = client.post(
        "/console/admin/users/tom.analyst/roles",
        data={"roles": ["analyst", "admin"]},
        headers={"X-Csrf": admin_csrf},
    )
    assert r.status_code == 200

    # Same still-live tom session, re-used with no new login - now resolves as admin.
    r = tom_client.get("/console/admin/users", follow_redirects=False)
    assert r.status_code == 200


def test_reset_password_via_console(client_and_store):
    client, _store, _index, auth_store = client_and_store
    csrf = _login(client, "root.admin", "pw-admin")

    r = client.post(
        "/console/admin/users/tom.analyst/password", data={"password": "brand-new-pw"}, headers={"X-Csrf": csrf}
    )
    assert r.status_code == 200
    assert auth_store.verify_login("tom.analyst", "brand-new-pw") is not None


def test_disable_then_enable_user_via_console(client_and_store):
    client, _store, _index, auth_store = client_and_store
    csrf = _login(client, "root.admin", "pw-admin")

    r = client.post(
        "/console/admin/users/tom.analyst/disabled", data={"disabled": "1"}, headers={"X-Csrf": csrf}
    )
    assert r.status_code == 200
    assert auth_store.get_user("tom.analyst").disabled is True

    r = client.post(
        "/console/admin/users/tom.analyst/disabled", data={"disabled": "0"}, headers={"X-Csrf": csrf}
    )
    assert r.status_code == 200
    assert auth_store.get_user("tom.analyst").disabled is False


def test_last_admin_guard_refuses_disabling_the_sole_admin_via_console(client_and_store):
    """Real test per the acceptance criterion: the guard actually refuses the console action, not
    just the underlying store method in isolation."""
    client, _store, _index, auth_store = client_and_store
    csrf = _login(client, "root.admin", "pw-admin")

    r = client.post(
        "/console/admin/users/root.admin/disabled", data={"disabled": "1"}, headers={"X-Csrf": csrf}
    )
    assert r.status_code == 200  # never a raw 500
    assert "flash" in r.text
    assert "last" in r.text.lower() or "admin" in r.text.lower()
    assert auth_store.get_user("root.admin").disabled is False  # refused, not applied


def test_last_admin_guard_refuses_removing_admin_role_via_console(client_and_store):
    client, _store, _index, auth_store = client_and_store
    csrf = _login(client, "root.admin", "pw-admin")

    r = client.post(
        "/console/admin/users/root.admin/roles", data={"roles": ["analyst"]}, headers={"X-Csrf": csrf}
    )
    assert r.status_code == 200
    assert "flash" in r.text
    assert auth_store.get_user("root.admin").roles == "admin"  # refused, not applied


def test_role_change_is_audited_with_who_what_when(client_and_store):
    client, _store, _index, auth_store = client_and_store
    csrf = _login(client, "root.admin", "pw-admin")

    r = client.post(
        "/console/admin/users/tom.analyst/roles",
        data={"roles": ["analyst", "reviewer"]},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200

    entries = auth_store.audit_trail("tom.analyst")
    role_changes = [e for e in entries if e.action == "role_change"]
    assert len(role_changes) == 1
    assert role_changes[0].actor_id == "root.admin"
    assert role_changes[0].ts

    # Also visible on the rendered detail page's audit trail.
    r = client.get("/console/admin/users/tom.analyst")
    assert r.status_code == 200
    assert "role_change" in r.text
    assert "root.admin" in r.text


def test_issue_and_revoke_service_token_via_console(client_and_store):
    client, _store, _index, auth_store = client_and_store
    csrf = _login(client, "root.admin", "pw-admin")

    r = client.post("/console/admin/users/tom.analyst/tokens", headers={"X-Csrf": csrf})
    assert r.status_code == 200
    assert "service-account token issued" in r.text

    sessions = auth_store.list_sessions("tom.analyst")
    bearer = next(s for s in sessions if s.kind == "bearer")
    assert bearer.revoked is False

    r = client.post(
        f"/console/admin/users/tom.analyst/sessions/{bearer.token_hash}/revoke", headers={"X-Csrf": csrf}
    )
    assert r.status_code == 200
    revoked = next(s for s in auth_store.list_sessions("tom.analyst") if s.token_hash == bearer.token_hash)
    assert revoked.revoked is True


# -- index health (C14 fail-closed visibility) ---------------------------------------------------


def _identity(actor_id: str, role: Role) -> Identity:
    return Identity(id=actor_id, roles=frozenset({role}))


def test_index_health_lists_a_package_blocked_by_an_injected_secret(client_and_store, tmp_path):
    """Mirrors tests/test_ap_index.py::test_secret_salted_package_never_reaches_index's fixture
    pattern (an AWS-key-shaped secret injected into a copy of the gold-pack example)."""
    client, store, index, auth_store = client_and_store
    csrf = _login(client, "root.admin", "pw-admin")

    pkg_dir = tmp_path / "pkg-with-secret"
    shutil.copytree(EXAMPLE_PACKAGE, pkg_dir)
    (pkg_dir / "code" / "leaked_creds.py").write_text("AWS_KEY = 'AKIAABCDEFGHIJKLMNOP'\n", encoding="utf-8")
    manifest = load_manifest(pkg_dir)
    analyst_id = manifest["owners"]["analyst"]["id"]
    reviewer_id = manifest["owners"]["reviewer"]["id"]

    record = store.publish(pkg_dir, actor=_identity(analyst_id, Role.ANALYST))
    wf = ReviewWorkflow(store=store, policy=ReviewPolicy(gate_before_review=False))
    wf.transition(record.package_id, record.package_version, to_status="in_review", actor=_identity(analyst_id, Role.ANALYST))
    wf.transition(record.package_id, record.package_version, to_status="approved", actor=_identity(reviewer_id, Role.REVIEWER))
    report = reindex_package(
        store=store, index=index, store_root=store.root,
        package_id=record.package_id, package_version=record.package_version,
    )
    assert report.blocked is True  # fixture sanity check

    r = client.get("/console/admin/index-health")
    assert r.status_code == 200
    assert record.package_id in r.text
    assert (report.block_reason or "secret") in r.text or "secret" in r.text.lower()

    # The re-run button calls the real reindex hook - still blocked (immutable content), but the
    # route must not 500 and must re-render the (still non-empty) list.
    r = client.post(
        f"/console/admin/index-health/{record.package_id}/{record.package_version}/reindex",
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200
    assert record.package_id in r.text


def test_index_health_empty_when_nothing_blocked(client_and_store):
    client, _store, _index, _auth = client_and_store
    _login(client, "root.admin", "pw-admin")
    r = client.get("/console/admin/index-health")
    assert r.status_code == 200
    assert "No approved package is currently blocked" in r.text


# -- settings -------------------------------------------------------------------------------------


def test_settings_retention_edit_round_trips_and_is_audited(client_and_store):
    client, store, _index, _auth = client_and_store
    csrf = _login(client, "root.admin", "pw-admin")

    r = client.post("/console/admin/settings", data={"retention_days": "120"}, headers={"X-Csrf": csrf})
    assert r.status_code == 200
    assert store.get_setting("retention_days") == "120"

    entries = store.settings_audit_trail("retention_days")
    assert entries and entries[0]["new_value"] == "120" and entries[0]["actor_id"] == "root.admin"

    r = client.get("/console/admin/settings")
    assert r.status_code == 200
    assert "120" in r.text


def test_settings_rejects_non_positive_retention(client_and_store):
    client, store, _index, _auth = client_and_store
    csrf = _login(client, "root.admin", "pw-admin")

    r = client.post("/console/admin/settings", data={"retention_days": "0"}, headers={"X-Csrf": csrf})
    assert r.status_code == 200
    assert "flash" in r.text
    assert store.get_setting("retention_days") is None


def test_settings_effective_config_panel_renders(client_and_store):
    client, _store, _index, _auth = client_and_store
    _login(client, "root.admin", "pw-admin")
    r = client.get("/console/admin/settings")
    assert r.status_code == 200
    assert "Effective configuration" in r.text
    assert "AP_STANDARD_REGISTRY_ROOT" in r.text


# -- registry state on the Standard changelog page -------------------------------------------------


def test_standard_changelog_shows_registry_pointer_state(client_and_store, tmp_path):
    import ap_api.deps as api_deps
    from ap_proposals.store import ProposalStore
    from ap_registry.profile_registry import ProfileRegistry

    client, _store, _index, _auth = client_and_store
    proposal_store = ProposalStore(tmp_path / "store")
    app.dependency_overrides[api_deps.get_proposal_store] = lambda: proposal_store
    try:
        registry = ProfileRegistry(proposal_store.root)
        registry.ensure_seeded("commodity_commit_forecast")

        _login(client, "root.admin", "pw-admin")
        r = client.get("/console/standard/changelog")
        assert r.status_code == 200
        assert "commodity_commit_forecast" in r.text
        assert "0.1" in r.text
    finally:
        proposal_store.close()


# -- team bot access (P5.4) -----------------------------------------------------------------------


def test_team_bot_post_routes_403_for_non_admin_identity(client_and_store):
    client, _store, _index, _auth = client_and_store
    csrf = _login(client, "tom.analyst", "pw-tom")
    r = client.post(
        "/console/admin/team-bot",
        data={"fathm_user_id": "planner.x", "display_name": "X", "telegram_user_id": "1"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 403


def test_provision_team_bot_creates_user_token_and_allowlist_row(client_and_store, tmp_path):
    client, _store, _index, auth_store = client_and_store
    csrf = _login(client, "root.admin", "pw-admin")

    r = client.post(
        "/console/admin/team-bot",
        data={
            "fathm_user_id": "planner.alice",
            "display_name": "Alice Planner",
            "telegram_user_id": "555000111",
        },
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200
    assert "provisioned" in r.text.lower()

    # 1. Service-account user created, no password, default team_reader role.
    user = auth_store.get_user("planner.alice")
    assert user is not None
    assert user.has_password is False
    assert user.roles == "team_reader"
    assert user.disabled is False

    # 2. A live (non-revoked) bearer token exists for that user.
    bearer_sessions = [s for s in auth_store.list_sessions("planner.alice") if s.kind == "bearer"]
    assert len(bearer_sessions) == 1
    assert bearer_sessions[0].revoked is False

    # 3. The allowlist file gets the correct entry, written atomically.
    allowlist_path = tmp_path / "chat_telegram_allowlist.json"
    entries = read_entries(allowlist_path)
    assert set(entries) == {"555000111"}
    assert entries["555000111"].fathm_user_id == "planner.alice"
    assert list(allowlist_path.parent.glob(".allowlist-*.tmp")) == []

    # The access-list table renders the provisioned member.
    assert "555000111" in r.text
    assert "planner.alice" in r.text


def test_provision_team_bot_with_explicit_roles(client_and_store, tmp_path):
    client, _store, _index, auth_store = client_and_store
    csrf = _login(client, "root.admin", "pw-admin")

    r = client.post(
        "/console/admin/team-bot",
        data={
            "fathm_user_id": "planner.bob",
            "display_name": "Bob Planner",
            "telegram_user_id": "555000222",
            "roles": ["team_reader", "company_reader"],
        },
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200
    user = auth_store.get_user("planner.bob")
    assert set(user.roles.split(",")) == {"team_reader", "company_reader"}


def test_raw_token_never_appears_in_the_provisioning_response_or_access_list(client_and_store, tmp_path):
    """Real test per the acceptance criterion: the raw bearer token is never displayed (unlike the
    users & access tab's one-time-shown token issuance) - it goes straight into the allowlist file
    and the console never echoes it back."""
    client, _store, _index, auth_store = client_and_store
    csrf = _login(client, "root.admin", "pw-admin")

    r = client.post(
        "/console/admin/team-bot",
        data={"fathm_user_id": "planner.carol", "display_name": "Carol", "telegram_user_id": "555000333"},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200

    allowlist_path = tmp_path / "chat_telegram_allowlist.json"
    raw_token = read_entries(allowlist_path)["555000333"].token
    assert raw_token not in r.text

    # And the access-list re-render (GET) never leaks it either.
    r2 = client.get("/console/admin/team-bot")
    assert raw_token not in r2.text


def test_revoke_team_bot_removes_allowlist_row_and_disables_the_token(client_and_store, tmp_path):
    client, _store, _index, auth_store = client_and_store
    csrf = _login(client, "root.admin", "pw-admin")

    client.post(
        "/console/admin/team-bot",
        data={"fathm_user_id": "planner.dave", "display_name": "Dave", "telegram_user_id": "555000444"},
        headers={"X-Csrf": csrf},
    )
    allowlist_path = tmp_path / "chat_telegram_allowlist.json"
    raw_token = read_entries(allowlist_path)["555000444"].token

    r = client.post("/console/admin/team-bot/555000444/revoke", headers={"X-Csrf": csrf})
    assert r.status_code == 200
    assert "revoked" in r.text.lower()

    # Allowlist row is gone.
    assert "555000444" not in read_entries(allowlist_path)

    # The user is disabled, and a disabled user's token resolves to no identity - real test against
    # AuthStore, not just a status flag.
    assert auth_store.get_user("planner.dave").disabled is True
    assert auth_store.identity_for_token(raw_token) is None


def test_provisioning_rejects_a_blank_telegram_id(client_and_store):
    client, _store, _index, auth_store = client_and_store
    csrf = _login(client, "root.admin", "pw-admin")

    r = client.post(
        "/console/admin/team-bot",
        data={"fathm_user_id": "planner.eve", "display_name": "Eve", "telegram_user_id": "   "},
        headers={"X-Csrf": csrf},
    )
    assert r.status_code == 200
    assert "flash" in r.text
    assert auth_store.get_user("planner.eve") is None  # nothing created on a rejected submit
