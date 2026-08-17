"""C10 package review workflow: full state machine, reject-requires-reason, gate-before-review knob."""

from __future__ import annotations

import pytest

from ap_agent_tools.tools import package_create
from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_review.policy import ReviewPolicy
from ap_review.workflow import ReviewPolicyError, ReviewWorkflow
from ap_store.store import PackageStore


def _identity(actor_id: str, role: Role) -> Identity:
    return Identity(id=actor_id, roles=frozenset({role}))


def _published(tmp_path, name: str = "pkg", analyst_id: str = "tom.analyst"):
    pkg_dir = package_create(tmp_path / name, title=f"{name} title", analyst_id=analyst_id)
    store = PackageStore(tmp_path / "store")
    record = store.publish(pkg_dir, actor=_identity(analyst_id, Role.ANALYST))
    return store, record


def test_full_state_machine_happy_path(tmp_path):
    store, record = _published(tmp_path)
    wf = ReviewWorkflow(store=store)

    rec = wf.transition(
        record.package_id, record.package_version, to_status="in_review", actor=_identity("tom.analyst", Role.ANALYST)
    )
    assert rec.status == "in_review"

    rec = wf.transition(
        record.package_id, record.package_version, to_status="approved", actor=_identity("jane.lead", Role.REVIEWER)
    )
    assert rec.status == "approved"
    store.close()


def test_reject_requires_reason(tmp_path):
    store, record = _published(tmp_path)
    wf = ReviewWorkflow(store=store)
    wf.transition(record.package_id, record.package_version, to_status="in_review", actor=_identity("tom.analyst", Role.ANALYST))

    with pytest.raises(ReviewPolicyError, match="reason"):
        wf.transition(record.package_id, record.package_version, to_status="rejected", actor=_identity("jane.lead", Role.REVIEWER))

    with pytest.raises(ReviewPolicyError, match="reason"):
        wf.transition(
            record.package_id, record.package_version, to_status="rejected", actor=_identity("jane.lead", Role.REVIEWER), reason="   "
        )

    rec = wf.transition(
        record.package_id,
        record.package_version,
        to_status="rejected",
        actor=_identity("jane.lead", Role.REVIEWER),
        reason="missing evidence for override",
    )
    assert rec.status == "rejected"
    store.close()


def test_rejected_can_be_revised_back_to_draft(tmp_path):
    store, record = _published(tmp_path)
    wf = ReviewWorkflow(store=store)
    wf.transition(record.package_id, record.package_version, to_status="in_review", actor=_identity("tom.analyst", Role.ANALYST))
    wf.transition(
        record.package_id, record.package_version, to_status="rejected", actor=_identity("jane.lead", Role.REVIEWER), reason="fix it"
    )
    rec = wf.transition(record.package_id, record.package_version, to_status="draft", actor=_identity("tom.analyst", Role.ANALYST))
    assert rec.status == "draft"
    store.close()


def test_admin_can_withdraw_or_revise_a_package_they_do_not_own(tmp_path):
    store, record = _published(tmp_path)
    wf = ReviewWorkflow(store=store)
    admin = Identity(id="ops.admin", roles=frozenset({Role.ADMIN}))

    wf.transition(record.package_id, record.package_version, to_status="in_review", actor=_identity("tom.analyst", Role.ANALYST))
    rec = wf.transition(record.package_id, record.package_version, to_status="draft", actor=admin)
    assert rec.status == "draft"

    wf.transition(record.package_id, record.package_version, to_status="in_review", actor=_identity("tom.analyst", Role.ANALYST))
    wf.transition(
        record.package_id, record.package_version, to_status="rejected", actor=_identity("jane.lead", Role.REVIEWER), reason="fix it"
    )
    rec = wf.transition(record.package_id, record.package_version, to_status="draft", actor=admin)
    assert rec.status == "draft"
    store.close()


def test_non_owner_non_admin_cannot_withdraw_or_revise_someone_elses_package(tmp_path):
    """D3: a leaked non-owning bearer token (e.g. a team_reader chat service account) must not be
    able to pull someone else's package back to draft."""
    store, record = _published(tmp_path)
    wf = ReviewWorkflow(store=store)
    intruder = _identity("eve.reader", Role.TEAM_READER)

    wf.transition(record.package_id, record.package_version, to_status="in_review", actor=_identity("tom.analyst", Role.ANALYST))
    with pytest.raises(ReviewPolicyError, match="may not withdraw/revise"):
        wf.transition(record.package_id, record.package_version, to_status="draft", actor=intruder)

    wf.transition(
        record.package_id, record.package_version, to_status="rejected", actor=_identity("jane.lead", Role.REVIEWER), reason="fix it"
    )
    with pytest.raises(ReviewPolicyError, match="may not withdraw/revise"):
        wf.transition(record.package_id, record.package_version, to_status="draft", actor=intruder)
    store.close()


def test_self_review_blocked_by_default_and_allowed_when_overridden(tmp_path):
    store, record = _published(tmp_path)
    wf_default = ReviewWorkflow(store=store)
    wf_default.transition(
        record.package_id, record.package_version, to_status="in_review", actor=_identity("tom.analyst", Role.ANALYST)
    )
    with pytest.raises(ReviewPolicyError, match="allow_self_review"):
        wf_default.transition(
            record.package_id, record.package_version, to_status="approved", actor=_identity("tom.analyst", Role.REVIEWER)
        )

    wf_override = ReviewWorkflow(store=store, policy=ReviewPolicy(allow_self_review=True))
    rec = wf_override.transition(
        record.package_id, record.package_version, to_status="approved", actor=_identity("tom.analyst", Role.REVIEWER)
    )
    assert rec.status == "approved"
    store.close()


def test_gate_before_review_blocks_failing_package_by_default(tmp_path):
    pkg_dir = package_create(tmp_path / "broken", title="Broken pack", analyst_id="tom.analyst")
    (pkg_dir / "outputs" / "RUN_SUMMARY.md").unlink()  # breaks output_contract_files

    store = PackageStore(tmp_path / "store")
    record = store.publish(pkg_dir, actor=_identity("tom.analyst", Role.ANALYST))
    assert record.gate_overall == "fail"  # publish records but does not block on gate failure

    wf = ReviewWorkflow(store=store)  # default: gate_before_review=True
    with pytest.raises(ReviewPolicyError, match="gate-before-review"):
        wf.transition(record.package_id, record.package_version, to_status="in_review", actor=_identity("tom.analyst", Role.ANALYST))

    wf_off = ReviewWorkflow(store=store, policy=ReviewPolicy(gate_before_review=False))
    rec = wf_off.transition(record.package_id, record.package_version, to_status="in_review", actor=_identity("tom.analyst", Role.ANALYST))
    assert rec.status == "in_review"
    store.close()


def test_analyst_role_required_to_submit(tmp_path):
    store, record = _published(tmp_path)
    wf = ReviewWorkflow(store=store)
    with pytest.raises(ReviewPolicyError, match="analyst role"):
        wf.transition(
            record.package_id, record.package_version, to_status="in_review", actor=_identity("bob.reader", Role.TEAM_READER)
        )
    store.close()


def test_reviewer_role_required_to_decide(tmp_path):
    store, record = _published(tmp_path)
    wf = ReviewWorkflow(store=store)
    wf.transition(record.package_id, record.package_version, to_status="in_review", actor=_identity("tom.analyst", Role.ANALYST))
    with pytest.raises(ReviewPolicyError, match="reviewer role"):
        wf.transition(
            record.package_id, record.package_version, to_status="approved", actor=_identity("bob.reader", Role.TEAM_READER)
        )
    store.close()


def test_admin_bypasses_role_and_self_review_checks(tmp_path):
    store, record = _published(tmp_path)
    wf = ReviewWorkflow(store=store)
    admin = Identity(id="tom.analyst", roles=frozenset({Role.ADMIN}))
    wf.transition(record.package_id, record.package_version, to_status="in_review", actor=admin)
    rec = wf.transition(record.package_id, record.package_version, to_status="approved", actor=admin)
    assert rec.status == "approved"
    store.close()


def test_invalid_transition_is_rejected(tmp_path):
    store, record = _published(tmp_path)
    wf = ReviewWorkflow(store=store)
    with pytest.raises(ReviewPolicyError, match="not an allowed review transition"):
        wf.transition(record.package_id, record.package_version, to_status="approved", actor=_identity("jane.lead", Role.REVIEWER))
    store.close()
