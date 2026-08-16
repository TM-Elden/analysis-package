"""C11 identity scaffold + audit trail on state-changing actions."""

from __future__ import annotations

import pytest

from ap_agent_tools.tools import package_create
from ap_auth.identity import Identity, IdentityError, identity_from_env, parse_roles
from ap_auth.roles import Role
from ap_review.workflow import ReviewWorkflow
from ap_store.store import PackageStore


def test_identity_requires_nonempty_id_and_roles():
    with pytest.raises(IdentityError):
        Identity(id="", roles=frozenset({Role.ANALYST}))
    with pytest.raises(IdentityError):
        Identity(id="tom", roles=frozenset())


def test_parse_roles_rejects_unknown_role_and_accepts_known():
    with pytest.raises(IdentityError):
        parse_roles("not_a_real_role")
    assert parse_roles("analyst, reviewer") == frozenset({Role.ANALYST, Role.REVIEWER})


def test_admin_role_bypasses_has_role_checks():
    identity = Identity(id="root", roles=frozenset({Role.ADMIN}))
    assert identity.has_role(Role.REVIEWER)
    assert identity.has_role(Role.ANALYST)
    assert not Identity(id="tom", roles=frozenset({Role.ANALYST})).has_role(Role.REVIEWER)


def test_identity_from_env(monkeypatch):
    monkeypatch.setenv("AP_ACTOR_ID", "tom.analyst")
    monkeypatch.setenv("AP_ACTOR_ROLES", "analyst,reviewer")
    identity = identity_from_env()
    assert identity.id == "tom.analyst"
    assert identity.roles == frozenset({Role.ANALYST, Role.REVIEWER})


def test_identity_from_env_missing_raises(monkeypatch):
    monkeypatch.delenv("AP_ACTOR_ID", raising=False)
    monkeypatch.delenv("AP_ACTOR_ROLES", raising=False)
    with pytest.raises(IdentityError):
        identity_from_env()


def test_audit_trail_records_actor_role_and_reason_on_every_transition(tmp_path):
    pkg_dir = package_create(tmp_path / "pkg", title="Audit pack", analyst_id="tom.analyst")
    store = PackageStore(tmp_path / "store")
    record = store.publish(pkg_dir, actor=Identity(id="tom.analyst", roles=frozenset({Role.ANALYST})))

    wf = ReviewWorkflow(store=store)
    wf.transition(
        record.package_id,
        record.package_version,
        to_status="in_review",
        actor=Identity(id="tom.analyst", roles=frozenset({Role.ANALYST})),
    )
    wf.transition(
        record.package_id,
        record.package_version,
        to_status="rejected",
        actor=Identity(id="jane.lead", roles=frozenset({Role.REVIEWER})),
        reason="needs more evidence",
    )

    trail = store.audit_trail(record.package_id, record.package_version)
    assert [e.to_status for e in trail] == ["draft", "in_review", "rejected"]
    assert trail[0].from_status is None
    assert trail[0].actor_id == "tom.analyst"
    assert trail[1].actor_id == "tom.analyst"
    assert trail[2].actor_id == "jane.lead"
    assert trail[2].actor_roles == "reviewer"
    assert trail[2].reason == "needs more evidence"
    # no bare-string actor ever recorded - every row carries a real identity id
    assert all(e.actor_id for e in trail)
    store.close()
