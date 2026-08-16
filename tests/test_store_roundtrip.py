"""C3 package store: persist/retrieve/list/immutability."""

from __future__ import annotations

import pytest

from ap_agent_tools.tools import package_create
from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_store.store import ImmutabilityError, ListFilter, PackageStore


def _analyst(actor_id: str = "tom.analyst") -> Identity:
    return Identity(id=actor_id, roles=frozenset({Role.ANALYST}))


def test_publish_persist_retrieve_list(tmp_path):
    pkg_dir = package_create(tmp_path / "pkg", title="Roundtrip pack", analyst_id="tom.analyst")
    store = PackageStore(tmp_path / "store")
    record = store.publish(pkg_dir, actor=_analyst())

    fetched = store.get(record.package_id, record.package_version)
    assert fetched is not None
    assert fetched.package_id == record.package_id
    assert fetched.status == "draft"
    assert fetched.gate_overall == "pass"
    assert fetched.owners()["analyst"]["id"] == "tom.analyst"

    latest = store.get(record.package_id)
    assert latest is not None
    assert latest.package_version == record.package_version

    page = store.list(ListFilter(profile="commodity_commit_forecast/0.1"))
    assert page.total == 1
    assert page.items[0].package_id == record.package_id

    dest = tmp_path / "extracted"
    store.extract(record.package_id, record.package_version, dest)
    assert (dest / "MANIFEST.yaml").is_file()
    assert (dest / "outputs" / "supplier_forecast.csv").is_file()
    store.close()


def test_get_missing_package_returns_none(tmp_path):
    store = PackageStore(tmp_path / "store")
    assert store.get("pkg_does_not_exist") is None
    store.close()


def test_publish_is_idempotent_for_identical_content(tmp_path):
    pkg_dir = package_create(tmp_path / "pkg", title="Idempotent pack", analyst_id="tom.analyst")
    store = PackageStore(tmp_path / "store")
    r1 = store.publish(pkg_dir, actor=_analyst())
    r2 = store.publish(pkg_dir, actor=_analyst())
    assert r1.blob_sha256 == r2.blob_sha256
    assert store.list().total == 1  # republish did not duplicate the row
    store.close()


def test_publish_rejects_mutation_of_same_version(tmp_path):
    pkg_dir = package_create(tmp_path / "pkg", title="Immutable pack", analyst_id="tom.analyst")
    store = PackageStore(tmp_path / "store")
    store.publish(pkg_dir, actor=_analyst())

    (pkg_dir / "outputs" / "RUN_SUMMARY.md").write_text("mutated after publish\n", encoding="utf-8")
    with pytest.raises(ImmutabilityError):
        store.publish(pkg_dir, actor=_analyst())
    store.close()


def test_bumping_package_version_is_a_new_immutable_row(tmp_path):
    import yaml

    pkg_dir = package_create(tmp_path / "pkg", title="Editable pack", analyst_id="tom.analyst")
    store = PackageStore(tmp_path / "store")
    r1 = store.publish(pkg_dir, actor=_analyst())

    manifest_path = pkg_dir / "MANIFEST.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["package_version"] = "1.0.1"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    r2 = store.publish(pkg_dir, actor=_analyst())
    assert r2.package_id == r1.package_id
    assert r2.package_version == "1.0.1"
    assert store.get(r1.package_id, "1.0.0") is not None  # old version still retrievable
    assert store.get(r1.package_id, "1.0.1") is not None
    store.close()


def test_list_pagination_and_filters(tmp_path):
    store = PackageStore(tmp_path / "store")
    for i in range(3):
        pkg_dir = package_create(tmp_path / f"pkg{i}", title=f"Pack {i}", analyst_id="tom.analyst")
        store.publish(pkg_dir, actor=_analyst())

    page1 = store.list(ListFilter(page=1, page_size=2))
    assert page1.total == 3
    assert len(page1.items) == 2
    page2 = store.list(ListFilter(page=2, page_size=2))
    assert len(page2.items) == 1

    filtered = store.list(ListFilter(query="Pack 1"))
    assert filtered.total == 1
    assert filtered.items[0].title == "Pack 1"

    by_owner = store.list(ListFilter(owner="tom.analyst"))
    assert by_owner.total == 3
    store.close()
