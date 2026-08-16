"""C6/C7 proposal workflow: full lifecycle, decision policy, approve-with-edits, audit trail."""

from __future__ import annotations

import pytest

from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_proposals.kinds import ProposalValidationError
from ap_proposals.store import ListFilter, ProposalStore, ProposalStoreError
from ap_proposals.workflow import ProposalPolicyError, ProposalWorkflow


def _identity(actor_id: str, role: Role) -> Identity:
    return Identity(id=actor_id, roles=frozenset({role}))


def _profile_change_diff(code: str = "SUPPLIER_CHANGE") -> dict:
    return {
        "profile": "commodity",
        "file": "reason_codes.json",
        "before": {"codes": []},
        "after": {"codes": [code]},
    }


def _created(tmp_path, kind: str = "profile_change", diff: dict | None = None):
    store = ProposalStore(tmp_path / "store")
    wf = ProposalWorkflow(store=store)
    record = wf.create(
        kind=kind,
        summary="Add SUPPLIER_CHANGE reason code",
        rationale="Seen 12 times in the last 30 days of override evidence",
        diff=diff if diff is not None else _profile_change_diff(),
        evidence={"package_ids": ["pkg-1", "pkg-2"]},
        actor=_identity("sweep.bot", Role.ANALYST),
    )
    return store, wf, record


def test_full_lifecycle_create_then_approve(tmp_path):
    store, wf, record = _created(tmp_path)
    assert record.proposal_id.startswith("prop_")
    assert record.status == "pending_hitl"
    assert record.decided_by_id is None

    approved = wf.decide(
        record.proposal_id, to_status="approved", actor=_identity("cap.tan", Role.STANDARD_APPROVER)
    )
    assert approved.status == "approved"
    assert approved.decided_by_id == "cap.tan"
    assert approved.decided_at is not None
    assert approved.edited_diff() is None
    store.close()


def test_full_lifecycle_create_then_reject(tmp_path):
    store, wf, record = _created(tmp_path)
    rejected = wf.decide(
        record.proposal_id,
        to_status="rejected",
        actor=_identity("cap.tan", Role.STANDARD_APPROVER),
        reason="not enough corpus evidence yet",
    )
    assert rejected.status == "rejected"
    assert rejected.decision_reason == "not enough corpus evidence yet"
    store.close()


def test_full_lifecycle_create_then_withdraw(tmp_path):
    store, wf, record = _created(tmp_path)
    withdrawn = wf.decide(record.proposal_id, to_status="withdrawn", actor=_identity("sweep.bot", Role.ANALYST))
    assert withdrawn.status == "withdrawn"
    store.close()


def test_edited_diff_rejected_on_withdraw(tmp_path):
    """edited_diff is only meaningful on an approve decision - this must hold for every decision
    path, not just approve/reject. A withdraw carrying a (possibly malformed) edited_diff must be
    rejected before it can reach the store, otherwise an unvalidated, schema-unchecked diff would
    be persisted on a withdrawn proposal."""
    store, wf, record = _created(tmp_path)
    with pytest.raises(ProposalPolicyError, match="only meaningful on an approve"):
        wf.decide(
            record.proposal_id,
            to_status="withdrawn",
            actor=_identity("sweep.bot", Role.ANALYST),
            edited_diff={"not": "a valid diff shape at all"},
        )
    # the transition must not have gone through - proposal is still pending, nothing persisted.
    reloaded = store.get(record.proposal_id)
    assert reloaded.status == "pending_hitl"
    assert reloaded.edited_diff() is None
    store.close()


def test_reject_requires_reason(tmp_path):
    store, wf, record = _created(tmp_path)
    with pytest.raises(ProposalPolicyError, match="decision_reason"):
        wf.decide(record.proposal_id, to_status="rejected", actor=_identity("cap.tan", Role.STANDARD_APPROVER))

    with pytest.raises(ProposalPolicyError, match="decision_reason"):
        wf.decide(
            record.proposal_id, to_status="rejected", actor=_identity("cap.tan", Role.STANDARD_APPROVER), reason="   "
        )
    store.close()


def test_non_approver_cannot_decide(tmp_path):
    store, wf, record = _created(tmp_path)
    with pytest.raises(ProposalPolicyError, match="standard_approver"):
        wf.decide(record.proposal_id, to_status="approved", actor=_identity("bob.reader", Role.TEAM_READER))
    store.close()


def test_admin_bypasses_role_check(tmp_path):
    store, wf, record = _created(tmp_path)
    admin = Identity(id="root", roles=frozenset({Role.ADMIN}))
    approved = wf.decide(record.proposal_id, to_status="approved", actor=admin)
    assert approved.status == "approved"
    store.close()


def test_approve_with_edits_preserves_original_diff(tmp_path):
    store, wf, record = _created(tmp_path)
    edited = _profile_change_diff(code="SUPPLIER_CHANGE_V2")
    approved = wf.decide(
        record.proposal_id,
        to_status="approved",
        actor=_identity("cap.tan", Role.STANDARD_APPROVER),
        edited_diff=edited,
    )
    assert approved.status == "approved"
    assert approved.diff() == _profile_change_diff()  # original untouched
    assert approved.edited_diff() == edited
    store.close()


def test_edited_diff_only_valid_on_approve(tmp_path):
    store, wf, record = _created(tmp_path)
    with pytest.raises(ProposalPolicyError, match="only meaningful on an approve"):
        wf.decide(
            record.proposal_id,
            to_status="rejected",
            actor=_identity("cap.tan", Role.STANDARD_APPROVER),
            reason="no",
            edited_diff=_profile_change_diff(),
        )
    store.close()


def test_edited_diff_validated_against_kind_schema(tmp_path):
    store, wf, record = _created(tmp_path)
    with pytest.raises(ProposalValidationError):
        wf.decide(
            record.proposal_id,
            to_status="approved",
            actor=_identity("cap.tan", Role.STANDARD_APPROVER),
            edited_diff={"profile": "commodity"},  # missing required "file"/"after"
        )
    store.close()


def test_invalid_transition_is_rejected(tmp_path):
    store, wf, record = _created(tmp_path)
    wf.decide(record.proposal_id, to_status="approved", actor=_identity("cap.tan", Role.STANDARD_APPROVER))
    with pytest.raises(ProposalPolicyError, match="not an allowed proposal transition"):
        wf.decide(record.proposal_id, to_status="rejected", actor=_identity("cap.tan", Role.STANDARD_APPROVER), reason="x")
    store.close()


def test_create_rejects_malformed_diff(tmp_path):
    store = ProposalStore(tmp_path / "store")
    wf = ProposalWorkflow(store=store)
    with pytest.raises(ProposalValidationError):
        wf.create(
            kind="reason_code_add",
            summary="bad",
            rationale="bad",
            diff={"profile": "commodity"},  # missing required "code"/"description"
            evidence={},
            actor=_identity("sweep.bot", Role.ANALYST),
        )
    store.close()


def test_create_rejects_unknown_kind(tmp_path):
    store = ProposalStore(tmp_path / "store")
    wf = ProposalWorkflow(store=store)
    with pytest.raises(ProposalValidationError):
        wf.create(
            kind="not_a_real_kind",
            summary="bad",
            rationale="bad",
            diff={},
            evidence={},
            actor=_identity("sweep.bot", Role.ANALYST),
        )
    store.close()


def test_no_role_restriction_on_create(tmp_path):
    """Creating a proposal requires only an authenticated identity - no role gate (unlike deciding)."""
    store = ProposalStore(tmp_path / "store")
    wf = ProposalWorkflow(store=store)
    record = wf.create(
        kind="check_add",
        summary="new check",
        rationale="found a gap",
        diff={"check_id": "new_check", "severity": "advisory", "description": "..."},
        evidence={},
        actor=_identity("bob.reader", Role.TEAM_READER),
    )
    assert record.status == "pending_hitl"
    store.close()


def test_decide_missing_proposal_raises(tmp_path):
    store = ProposalStore(tmp_path / "store")
    wf = ProposalWorkflow(store=store)
    with pytest.raises(ProposalStoreError, match="no such proposal"):
        wf.decide("prop_doesnotexist", to_status="approved", actor=_identity("cap.tan", Role.STANDARD_APPROVER))
    store.close()


def test_audit_trail_records_create_and_decision(tmp_path):
    store, wf, record = _created(tmp_path)
    wf.decide(
        record.proposal_id, to_status="rejected", actor=_identity("cap.tan", Role.STANDARD_APPROVER), reason="no"
    )
    trail = store.audit_trail(record.proposal_id)
    assert [e.to_status for e in trail] == ["pending_hitl", "rejected"]
    assert trail[0].actor_id == "sweep.bot"
    assert trail[0].from_status is None
    assert trail[1].actor_id == "cap.tan"
    assert trail[1].from_status == "pending_hitl"
    assert trail[1].reason == "no"
    store.close()


def test_list_filters_by_status_and_kind(tmp_path):
    store = ProposalStore(tmp_path / "store")
    wf = ProposalWorkflow(store=store)
    p1 = wf.create(
        kind="profile_change",
        summary="a",
        rationale="a",
        diff=_profile_change_diff(),
        evidence={},
        actor=_identity("sweep.bot", Role.ANALYST),
    )
    wf.create(
        kind="check_add",
        summary="b",
        rationale="b",
        diff={"check_id": "x", "severity": "required", "description": "d"},
        evidence={},
        actor=_identity("sweep.bot", Role.ANALYST),
    )
    wf.decide(p1.proposal_id, to_status="approved", actor=_identity("cap.tan", Role.STANDARD_APPROVER))

    page = store.list()
    assert page.total == 2

    approved_page = store.list(ListFilter(status="approved"))
    assert approved_page.total == 1
    assert approved_page.items[0].proposal_id == p1.proposal_id

    kind_page = store.list(ListFilter(kind="check_add"))
    assert kind_page.total == 1
    store.close()
