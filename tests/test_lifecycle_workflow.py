"""C12 package lifecycle: LifecycleWorkflow's supersede/recall/restore/legal-hold/purge state
machine and PackageStore's underlying mechanism (link_replaces / set_legal_hold / purge blob
refcount), at the workflow/store layer - see test_lifecycle_api.py for the HTTP-route-level tests
(including the reindex-wiring fix)."""

from __future__ import annotations

import pytest

from ap_agent_tools.tools import package_create
from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_lifecycle.workflow import LifecyclePolicyError, LifecycleWorkflow
from ap_store.store import PackageStore


def _identity(actor_id: str, *roles: Role) -> Identity:
    return Identity(id=actor_id, roles=frozenset(roles))


def _approved(store: PackageStore, tmp_path, name: str, analyst_id: str = "tom.analyst"):
    from ap_review.workflow import ReviewWorkflow

    pkg_dir = package_create(tmp_path / name, title=f"{name} title", analyst_id=analyst_id)
    record = store.publish(pkg_dir, actor=_identity(analyst_id, Role.ANALYST))
    wf = ReviewWorkflow(store=store)
    wf.transition(record.package_id, record.package_version, to_status="in_review", actor=_identity(analyst_id, Role.ANALYST))
    return wf.transition(record.package_id, record.package_version, to_status="approved", actor=_identity("jane.lead", Role.REVIEWER))


@pytest.fixture()
def store(tmp_path):
    s = PackageStore(tmp_path / "store")
    yield s
    s.close()


# -- supersede --------------------------------------------------------------------------------


def test_supersede_requires_approved_successor(store, tmp_path):
    a = _approved(store, tmp_path, "a")
    lw = LifecycleWorkflow(store=store)
    with pytest.raises(LifecyclePolicyError, match="approved"):
        lw.supersede(
            a.package_id,
            a.package_version,
            successor_package_id="does-not-exist",
            successor_package_version="1.0.0",
            actor=_identity("jane.lead", Role.REVIEWER),
        )


def test_supersede_happy_path_links_successor_and_flips_status(store, tmp_path):
    a = _approved(store, tmp_path, "a")
    b = _approved(store, tmp_path, "b")
    lw = LifecycleWorkflow(store=store)

    updated = lw.supersede(
        a.package_id,
        a.package_version,
        successor_package_id=b.package_id,
        successor_package_version=b.package_version,
        actor=_identity("jane.lead", Role.REVIEWER),
        reason="superseded by a corrected forecast",
    )
    assert updated.status == "superseded"

    successor = store.get(b.package_id, b.package_version)
    assert successor.replaces_package_id == a.package_id
    assert successor.replaces_package_version == a.package_version


def test_supersede_requires_reviewer_or_admin(store, tmp_path):
    a = _approved(store, tmp_path, "a")
    b = _approved(store, tmp_path, "b")
    lw = LifecycleWorkflow(store=store)
    with pytest.raises(LifecyclePolicyError, match="reviewer"):
        lw.supersede(
            a.package_id,
            a.package_version,
            successor_package_id=b.package_id,
            successor_package_version=b.package_version,
            actor=_identity("tom.analyst", Role.ANALYST),
        )


# -- recall -------------------------------------------------------------------------------------


def test_recall_requires_non_empty_reason(store, tmp_path):
    a = _approved(store, tmp_path, "a")
    lw = LifecycleWorkflow(store=store)
    with pytest.raises(LifecyclePolicyError, match="reason"):
        lw.recall(a.package_id, a.package_version, actor=_identity("jane.lead", Role.REVIEWER), reason="   ")


def test_recall_happy_path(store, tmp_path):
    a = _approved(store, tmp_path, "a")
    lw = LifecycleWorkflow(store=store)
    updated = lw.recall(a.package_id, a.package_version, actor=_identity("jane.lead", Role.REVIEWER), reason="data quality issue")
    assert updated.status == "recalled"


# -- restore ------------------------------------------------------------------------------------


def test_restore_recalled_requires_admin(store, tmp_path):
    a = _approved(store, tmp_path, "a")
    lw = LifecycleWorkflow(store=store)
    lw.recall(a.package_id, a.package_version, actor=_identity("jane.lead", Role.REVIEWER), reason="oops")

    with pytest.raises(LifecyclePolicyError, match="admin"):
        lw.restore(a.package_id, a.package_version, actor=_identity("jane.lead", Role.REVIEWER))

    updated = lw.restore(a.package_id, a.package_version, actor=_identity("root.admin", Role.ADMIN))
    assert updated.status == "approved"


def test_restore_superseded_requires_admin(store, tmp_path):
    a = _approved(store, tmp_path, "a")
    b = _approved(store, tmp_path, "b")
    lw = LifecycleWorkflow(store=store)
    lw.supersede(
        a.package_id,
        a.package_version,
        successor_package_id=b.package_id,
        successor_package_version=b.package_version,
        actor=_identity("jane.lead", Role.REVIEWER),
    )
    updated = lw.restore(a.package_id, a.package_version, actor=_identity("root.admin", Role.ADMIN))
    assert updated.status == "approved"


def test_restore_refuses_a_never_recalled_or_superseded_package(store, tmp_path):
    a = _approved(store, tmp_path, "a")
    lw = LifecycleWorkflow(store=store)
    with pytest.raises(LifecyclePolicyError, match="recalled.*superseded|superseded.*recalled"):
        lw.restore(a.package_id, a.package_version, actor=_identity("root.admin", Role.ADMIN))


# -- legal hold -----------------------------------------------------------------------------------


def test_legal_hold_requires_admin_and_a_reason_to_set(store, tmp_path):
    a = _approved(store, tmp_path, "a")
    lw = LifecycleWorkflow(store=store)

    with pytest.raises(LifecyclePolicyError, match="admin"):
        lw.set_legal_hold(a.package_id, a.package_version, hold=True, reason="litigation hold", actor=_identity("jane.lead", Role.REVIEWER))

    with pytest.raises(LifecyclePolicyError, match="reason"):
        lw.set_legal_hold(a.package_id, a.package_version, hold=True, reason=None, actor=_identity("root.admin", Role.ADMIN))

    updated = lw.set_legal_hold(a.package_id, a.package_version, hold=True, reason="litigation hold", actor=_identity("root.admin", Role.ADMIN))
    assert updated.legal_hold is True
    assert updated.legal_hold_reason == "litigation hold"

    cleared = lw.set_legal_hold(a.package_id, a.package_version, hold=False, reason=None, actor=_identity("root.admin", Role.ADMIN))
    assert cleared.legal_hold is False
    assert cleared.legal_hold_reason is None


def test_recall_and_supersede_still_work_under_legal_hold(store, tmp_path):
    """Hold blocks purge only - reversible status moves stay allowed under hold (freezing them
    would let a hold keep bad content live in the corpus)."""
    a = _approved(store, tmp_path, "a")
    b = _approved(store, tmp_path, "b")
    c = _approved(store, tmp_path, "c")
    lw = LifecycleWorkflow(store=store)
    lw.set_legal_hold(a.package_id, a.package_version, hold=True, reason="hold", actor=_identity("root.admin", Role.ADMIN))

    recalled = lw.recall(a.package_id, a.package_version, actor=_identity("jane.lead", Role.REVIEWER), reason="under hold, still recallable")
    assert recalled.status == "recalled"

    lw.set_legal_hold(b.package_id, b.package_version, hold=True, reason="hold", actor=_identity("root.admin", Role.ADMIN))
    superseded = lw.supersede(
        b.package_id,
        b.package_version,
        successor_package_id=c.package_id,  # c stays approved, valid successor
        successor_package_version=c.package_version,
        actor=_identity("jane.lead", Role.REVIEWER),
    )
    assert superseded.status == "superseded"


# -- purge ----------------------------------------------------------------------------------------


def test_purge_refuses_an_approved_package(store, tmp_path):
    a = _approved(store, tmp_path, "a")
    lw = LifecycleWorkflow(store=store)
    with pytest.raises(LifecyclePolicyError, match="approved"):
        lw.purge(a.package_id, a.package_version, actor=_identity("root.admin", Role.ADMIN))


def test_purge_refuses_a_held_package(store, tmp_path):
    a = _approved(store, tmp_path, "a")
    lw = LifecycleWorkflow(store=store)
    lw.recall(a.package_id, a.package_version, actor=_identity("jane.lead", Role.REVIEWER), reason="bad data")
    lw.set_legal_hold(a.package_id, a.package_version, hold=True, reason="litigation", actor=_identity("root.admin", Role.ADMIN))

    with pytest.raises(LifecyclePolicyError, match="legal hold"):
        lw.purge(a.package_id, a.package_version, actor=_identity("root.admin", Role.ADMIN))


def test_purge_requires_admin(store, tmp_path):
    a = _approved(store, tmp_path, "a")
    lw = LifecycleWorkflow(store=store)
    lw.recall(a.package_id, a.package_version, actor=_identity("jane.lead", Role.REVIEWER), reason="bad data")
    with pytest.raises(LifecyclePolicyError, match="admin"):
        lw.purge(a.package_id, a.package_version, actor=_identity("jane.lead", Role.REVIEWER))


def test_purge_tombstones_the_row_and_deletes_the_blob(store, tmp_path):
    a = _approved(store, tmp_path, "a")
    lw = LifecycleWorkflow(store=store)
    lw.recall(a.package_id, a.package_version, actor=_identity("jane.lead", Role.REVIEWER), reason="bad data")

    blob_path = store.blob_store._path_for(a.blob_sha256)
    assert blob_path.is_file()

    purged = lw.purge(a.package_id, a.package_version, actor=_identity("root.admin", Role.ADMIN), reason="retention")
    assert purged.purged_at is not None
    assert purged.status == "purged"
    assert purged.title == ""
    assert not blob_path.is_file()

    # audit rows, package_id/version, and status history all survive - it resolves to an honest
    # "purged" record rather than dangling.
    trail = store.audit_trail(a.package_id, a.package_version)
    assert trail[-1].to_status == "purged"


def test_purge_is_idempotent(store, tmp_path):
    a = _approved(store, tmp_path, "a")
    lw = LifecycleWorkflow(store=store)
    lw.recall(a.package_id, a.package_version, actor=_identity("jane.lead", Role.REVIEWER), reason="bad data")
    lw.purge(a.package_id, a.package_version, actor=_identity("root.admin", Role.ADMIN))
    again = lw.purge(a.package_id, a.package_version, actor=_identity("root.admin", Role.ADMIN))
    assert again.purged_at is not None


def _insert_synthetic_package_sharing_blob(store: PackageStore, *, package_id: str, blob_sha256: str, actor: Identity) -> None:
    """Test-only helper: insert a second `packages` row that references an existing blob's
    `blob_sha256` directly via SQL, bypassing `publish()`. Two *different* (package_id,
    package_version) pairs naturally sharing a blob would require byte-identical package
    directories - unreachable through the normal create/publish path since MANIFEST.yaml embeds
    each package's own package_id/package_version (see CLAUDE.md's immutability model) - so this
    is the direct way to set up PackageStore.purge's refcount precondition for a test."""
    with store._lock, store.conn:
        store.conn.execute(
            """INSERT INTO packages (
                package_id, package_version, profile, title, as_of, created_at, status,
                blob_sha256, analyst_id, reviewer_id, owners_json, gate_overall,
                published_by_id, published_by_roles
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                package_id,
                "1.0.0",
                "commodity_commit_forecast/0.1",
                "synthetic clone sharing a blob",
                "2025-01-01",
                "2025-01-01T00:00:00Z",
                "draft",
                blob_sha256,
                actor.id,
                None,
                "{}",
                "pass",
                actor.id,
                actor.roles_csv(),
            ),
        )


def test_purge_refcounts_shared_blobs_before_deleting(store, tmp_path):
    """The sharpest purge test: two package rows share one blob (content-addressed storage).
    Purging one must NOT delete the blob out from under the other - its export must still work."""
    a = _approved(store, tmp_path, "a")
    admin = _identity("root.admin", Role.ADMIN)
    _insert_synthetic_package_sharing_blob(store, package_id="clone-of-a", blob_sha256=a.blob_sha256, actor=admin)

    lw = LifecycleWorkflow(store=store)
    lw.recall(a.package_id, a.package_version, actor=_identity("jane.lead", Role.REVIEWER), reason="bad data")
    lw.purge(a.package_id, a.package_version, actor=admin)

    blob_path = store.blob_store._path_for(a.blob_sha256)
    assert blob_path.is_file(), "blob must survive - the clone still references it"
    # the surviving package's "export" still works.
    clone = store.get("clone-of-a", "1.0.0")
    assert store.blob_store.get(clone.blob_sha256) is not None

    # now purge the clone too (draft -> purgeable, not approved) - only then does the blob go.
    lw.purge("clone-of-a", "1.0.0", actor=admin)
    assert not blob_path.is_file()


# -- retention marker -------------------------------------------------------------------------


def test_retention_days_is_admin_only_and_defaults_to_unset(store):
    lw = LifecycleWorkflow(store=store)
    assert lw.get_retention_days() is None

    with pytest.raises(LifecyclePolicyError, match="admin"):
        lw.set_retention_days(90, actor=_identity("jane.lead", Role.REVIEWER))

    lw.set_retention_days(90, actor=_identity("root.admin", Role.ADMIN))
    assert lw.get_retention_days() == 90
