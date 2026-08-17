"""C12 lifecycle JSON API (`ap_api/lifecycle_routes.py`) + the reindex-wiring fix this task lands.

The sharpest test here is `test_recall_removes_chunks_and_approve_reindexes_them`: it proves, at
the real HTTP-route layer (not by calling `ap_index.reindex.reindex_package` directly like
test_ap_index.py does), that approving a package now actually reaches the C4 search index - the
real bug this task fixes - and that recalling one actually removes it.
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
from ap_index.models import SearchFilters
from ap_lifecycle.workflow import LifecycleWorkflow
from ap_store.store import PackageStore
from conftest import EXAMPLE_PACKAGE


@pytest.fixture()
def client_and_store(tmp_path):
    store = PackageStore(tmp_path / "store")
    index = IndexStore(tmp_path / "index")
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[deps.get_index] = lambda: index
    app.dependency_overrides[deps.get_auth_store] = lambda: auth_store

    auth_store.create_user("tom.analyst", display_name="Tom", roles=frozenset({Role.ANALYST}), password="pw-tom")
    auth_store.create_user("jane.lead", display_name="Jane", roles=frozenset({Role.REVIEWER}), password="pw-jane")
    auth_store.create_user("root.admin", display_name="Root", roles=frozenset({Role.ADMIN}), password="pw-root")

    client = TestClient(app, base_url="https://testserver")
    try:
        yield client, store, index, tmp_path, auth_store
    finally:
        app.dependency_overrides.clear()
        store.close()
        index.close()
        auth_store.close()


def _login(client: TestClient, user_id: str, password: str) -> dict:
    r = client.post("/login", json={"user_id": user_id, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _csrf(body: dict) -> dict:
    return {"X-Csrf": body["csrf_token"]}


def _chunk_count(index: IndexStore, package_id: str, package_version: str) -> int:
    results = index.search(None, filters=SearchFilters(package_id=package_id))
    return len([r for r in results if r.chunk.package_version == package_version])


def _publish_submit_approve(client: TestClient, store: PackageStore) -> dict:
    analyst = _login(client, "tom.analyst", "pw-tom")
    r = client.post("/packages", json={"package_dir": str(EXAMPLE_PACKAGE)}, headers=_csrf(analyst))
    assert r.status_code == 201, r.text
    pkg = r.json()

    r = client.post(
        f"/packages/{pkg['package_id']}/review",
        json={"package_version": pkg["package_version"], "to_status": "in_review"},
        headers=_csrf(analyst),
    )
    assert r.status_code == 200, r.text

    reviewer = _login(client, "jane.lead", "pw-jane")
    r = client.post(
        f"/packages/{pkg['package_id']}/review",
        json={"package_version": pkg["package_version"], "to_status": "approved"},
        headers=_csrf(reviewer),
    )
    assert r.status_code == 200, r.text
    return pkg


def test_approve_reaches_the_index_and_recall_removes_it(client_and_store):
    """The reindex-wiring fix, end to end via the real routes."""
    client, store, index, _tmp, _auth = client_and_store
    pkg = _publish_submit_approve(client, store)

    assert _chunk_count(index, pkg["package_id"], pkg["package_version"]) > 0, (
        "approving a package via POST /packages/{id}/review must now reach the C4 index - this "
        "was the live bug (reindex_package was correct but never called from any route)"
    )

    reviewer = _login(client, "jane.lead", "pw-jane")
    r = client.post(
        f"/packages/{pkg['package_id']}/recall",
        json={"package_version": pkg["package_version"], "reason": "data quality issue"},
        headers=_csrf(reviewer),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "recalled"

    assert _chunk_count(index, pkg["package_id"], pkg["package_version"]) == 0, (
        "a recalled package's chunks must actually be gone from the index - the sharpest trust "
        "test in this phase"
    )


def test_restore_reindexes_the_package(client_and_store):
    client, store, index, _tmp, _auth = client_and_store
    pkg = _publish_submit_approve(client, store)

    reviewer = _login(client, "jane.lead", "pw-jane")
    client.post(
        f"/packages/{pkg['package_id']}/recall",
        json={"package_version": pkg["package_version"], "reason": "oops"},
        headers=_csrf(reviewer),
    )
    assert _chunk_count(index, pkg["package_id"], pkg["package_version"]) == 0

    admin = _login(client, "root.admin", "pw-root")
    r = client.post(
        f"/packages/{pkg['package_id']}/restore",
        json={"package_version": pkg["package_version"]},
        headers=_csrf(admin),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert _chunk_count(index, pkg["package_id"], pkg["package_version"]) > 0


def test_recall_requires_reviewer_role_is_403(client_and_store):
    client, store, _index, _tmp, _auth = client_and_store
    pkg = _publish_submit_approve(client, store)
    analyst = _login(client, "tom.analyst", "pw-tom")
    r = client.post(
        f"/packages/{pkg['package_id']}/recall",
        json={"package_version": pkg["package_version"], "reason": "x"},
        headers=_csrf(analyst),
    )
    assert r.status_code == 403


def test_restore_requires_admin_is_403(client_and_store):
    client, store, _index, _tmp, _auth = client_and_store
    pkg = _publish_submit_approve(client, store)
    reviewer = _login(client, "jane.lead", "pw-jane")
    client.post(
        f"/packages/{pkg['package_id']}/recall",
        json={"package_version": pkg["package_version"], "reason": "oops"},
        headers=_csrf(reviewer),
    )
    r = client.post(
        f"/packages/{pkg['package_id']}/restore",
        json={"package_version": pkg["package_version"]},
        headers=_csrf(reviewer),
    )
    assert r.status_code == 403


def test_supersede_and_export(client_and_store):
    client, store, index, _tmp, _auth = client_and_store
    a = _publish_submit_approve(client, store)

    # a second, independently-published+approved package as the successor.
    analyst = _login(client, "tom.analyst", "pw-tom")
    import shutil

    second_dir = _tmp / "second-pkg"
    shutil.copytree(EXAMPLE_PACKAGE, second_dir)
    manifest_path = second_dir / "MANIFEST.yaml"
    text = manifest_path.read_text(encoding="utf-8")
    text = text.replace('package_id: "pkg_01hqexample000000000000001"', 'package_id: "pkg_second_example"')
    manifest_path.write_text(text, encoding="utf-8")

    r = client.post("/packages", json={"package_dir": str(second_dir)}, headers=_csrf(analyst))
    assert r.status_code == 201, r.text
    b = r.json()
    client.post(
        f"/packages/{b['package_id']}/review",
        json={"package_version": b["package_version"], "to_status": "in_review"},
        headers=_csrf(analyst),
    )
    reviewer = _login(client, "jane.lead", "pw-jane")
    client.post(
        f"/packages/{b['package_id']}/review",
        json={"package_version": b["package_version"], "to_status": "approved"},
        headers=_csrf(reviewer),
    )

    r = client.post(
        f"/packages/{a['package_id']}/supersede",
        json={
            "package_version": a["package_version"],
            "successor_package_id": b["package_id"],
            "successor_package_version": b["package_version"],
        },
        headers=_csrf(reviewer),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "superseded"
    assert _chunk_count(index, a["package_id"], a["package_version"]) == 0, "superseded packages leave the index entirely"

    r = client.get(f"/packages/{b['package_id']}/export", params={"version": b["package_version"]}, headers=_csrf(reviewer))
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/gzip"
    assert len(r.content) > 0


def test_export_requires_elevated_role(client_and_store):
    client, store, _index, _tmp, auth_store = client_and_store
    pkg = _publish_submit_approve(client, store)

    auth_store.create_user("ro.reader", display_name="Reader", roles=frozenset({Role.TEAM_READER}), password="pw-ro")
    reader = _login(client, "ro.reader", "pw-ro")

    r = client.get(f"/packages/{pkg['package_id']}/export", params={"version": pkg["package_version"]}, headers=_csrf(reader))
    assert r.status_code == 403


def test_export_succeeds_for_analyst(client_and_store):
    client, store, _index, _tmp, _auth = client_and_store
    pkg = _publish_submit_approve(client, store)
    analyst = _login(client, "tom.analyst", "pw-tom")
    r = client.get(f"/packages/{pkg['package_id']}/export", params={"version": pkg["package_version"]}, headers=_csrf(analyst))
    assert r.status_code == 200
    assert len(r.content) > 0


def test_export_of_a_purged_package_is_404_not_500(client_and_store):
    """`GET /packages/{id}/export` on a purged package must 404, not 500 - the blob a purge
    unlinks is exactly the blob `BlobStore.get` would otherwise raise a raw FileNotFoundError
    trying to read, so the route must reject a purged record before ever touching the blob store."""
    client, store, _index, _tmp, _auth = client_and_store
    pkg = _publish_submit_approve(client, store)

    admin_identity = Identity(id="root.admin", roles=frozenset({Role.ADMIN}))
    workflow = LifecycleWorkflow(store=store)
    workflow.recall(pkg["package_id"], pkg["package_version"], actor=admin_identity, reason="bad data")
    purged = workflow.purge(pkg["package_id"], pkg["package_version"], actor=admin_identity, reason="retention")
    assert purged.purged_at is not None

    admin = _login(client, "root.admin", "pw-root")
    r = client.get(
        f"/packages/{pkg['package_id']}/export", params={"version": pkg["package_version"]}, headers=_csrf(admin)
    )
    assert r.status_code == 404, r.text


def test_legal_hold_set_and_clear(client_and_store):
    client, store, _index, _tmp, _auth = client_and_store
    pkg = _publish_submit_approve(client, store)
    admin = _login(client, "root.admin", "pw-root")

    r = client.post(
        f"/packages/{pkg['package_id']}/legal-hold",
        json={"package_version": pkg["package_version"], "hold": True, "reason": "litigation"},
        headers=_csrf(admin),
    )
    assert r.status_code == 200, r.text
    assert r.json()["legal_hold"] is True

    r = client.post(
        f"/packages/{pkg['package_id']}/legal-hold",
        json={"package_version": pkg["package_version"], "hold": False},
        headers=_csrf(admin),
    )
    assert r.status_code == 200, r.text
    assert r.json()["legal_hold"] is False


def test_legal_hold_requires_admin(client_and_store):
    client, store, _index, _tmp, _auth = client_and_store
    pkg = _publish_submit_approve(client, store)
    reviewer = _login(client, "jane.lead", "pw-jane")
    r = client.post(
        f"/packages/{pkg['package_id']}/legal-hold",
        json={"package_version": pkg["package_version"], "hold": True, "reason": "x"},
        headers=_csrf(reviewer),
    )
    assert r.status_code == 403
