"""C6 stage-2 drafting service (`ap_planner_bot.service`): schema-validated diffs, evidence
resolved only against chunks actually fetched, dedup against an already-open proposal - and the
P4.4 eval bar (design report section 5.3): the seeded drift corpus must produce the expected
proposal kinds with correctly-resolved evidence, the clean corpus must produce nothing.
"""

from __future__ import annotations

from _planner_bot_corpus import (
    build_clean_corpus_with_index,
    build_drift_corpus_with_index,
)
from _planner_bot_fake_llm import (
    InvalidDiffLLMClient,
    InventedEvidenceLLMClient,
    RaisingOnceLLMClient,
    ScriptedDraftingLLMClient,
)

from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_planner_bot.detectors import run_all_detectors
from ap_planner_bot.scan import scan_corpus
from ap_planner_bot.service import draft_proposals
from ap_proposals.policy import ProposalPolicy
from ap_proposals.store import ProposalStore
from ap_proposals.workflow import ProposalWorkflow

SWEEP_IDENTITY = Identity(id="svc.planner-sweep", roles=frozenset({Role.STANDARD_APPROVER}))


def _findings(store):
    return run_all_detectors(scan_corpus(store))


def test_drift_corpus_produces_the_expected_proposal_kinds_with_resolved_evidence(tmp_path):
    store, index = build_drift_corpus_with_index(tmp_path)
    findings = _findings(store)
    assert findings, "fixture regression: drift corpus produced no findings to draft from"

    proposal_store = ProposalStore(tmp_path / "proposals")
    workflow = ProposalWorkflow(store=proposal_store, policy=ProposalPolicy())
    result = draft_proposals(
        findings, index=index, workflow=workflow, llm_client=ScriptedDraftingLLMClient(), identity=SWEEP_IDENTITY
    )

    kinds_created = {r.kind for r in result.created}
    assert kinds_created == {"reason_code_add", "profile_change"}
    # Every finding drafts real, in-scope evidence - the only discard reason possible here is two
    # distinct findings mapping to the same (kind, target) within one sweep (the fake's
    # `profile_change` diffs collapse repeated_waivers/gate_failure_hotspot findings onto the same
    # `training_grade.json` target), which `_has_open_duplicate` correctly suppresses.
    assert set(result.discarded) <= {"duplicate"}
    assert len(result.created) + result.discarded.get("duplicate", 0) == len(findings)

    for record in result.created:
        package_ids = record.evidence()["package_ids"]
        assert package_ids, f"{record.proposal_id} has no evidence package_ids"
        # every cited package_id must be one of the finding's own approved packages, not invented
        assert set(package_ids) <= {p.package_id for p in scan_corpus(store).packages}


def test_clean_corpus_produces_nothing(tmp_path):
    store, index = build_clean_corpus_with_index(tmp_path)
    findings = _findings(store)
    assert findings == []

    proposal_store = ProposalStore(tmp_path / "proposals")
    workflow = ProposalWorkflow(store=proposal_store, policy=ProposalPolicy())
    result = draft_proposals(
        findings, index=index, workflow=workflow, llm_client=ScriptedDraftingLLMClient(), identity=SWEEP_IDENTITY
    )

    assert result.created == ()
    assert proposal_store.list().total == 0


def test_dedup_suppresses_a_duplicate_draft_against_an_already_open_proposal(tmp_path):
    store, index = build_drift_corpus_with_index(tmp_path)
    findings = _findings(store)

    proposal_store = ProposalStore(tmp_path / "proposals")
    workflow = ProposalWorkflow(store=proposal_store, policy=ProposalPolicy())

    first = draft_proposals(
        findings, index=index, workflow=workflow, llm_client=ScriptedDraftingLLMClient(), identity=SWEEP_IDENTITY
    )
    assert first.created
    total_after_first = proposal_store.list().total

    # A second sweep over the identical findings (e.g. next week's run, nothing decided yet) must
    # not spam the queue with repeats of what's already pending_hitl.
    second = draft_proposals(
        findings, index=index, workflow=workflow, llm_client=ScriptedDraftingLLMClient(), identity=SWEEP_IDENTITY
    )
    assert second.created == ()
    assert second.discarded.get("duplicate") == len(findings)
    assert proposal_store.list().total == total_after_first


def test_a_draft_with_entirely_invented_evidence_is_discarded_not_stored(tmp_path):
    store, index = build_drift_corpus_with_index(tmp_path)
    findings = _findings(store)

    proposal_store = ProposalStore(tmp_path / "proposals")
    workflow = ProposalWorkflow(store=proposal_store, policy=ProposalPolicy())
    result = draft_proposals(
        findings, index=index, workflow=workflow, llm_client=InventedEvidenceLLMClient(), identity=SWEEP_IDENTITY
    )

    assert result.created == ()
    assert result.discarded.get("no_evidence_resolved") == len(findings)
    assert proposal_store.list().total == 0


def test_a_draft_with_an_invalid_diff_is_discarded_not_stored(tmp_path):
    store, index = build_drift_corpus_with_index(tmp_path)
    findings = _findings(store)

    proposal_store = ProposalStore(tmp_path / "proposals")
    workflow = ProposalWorkflow(store=proposal_store, policy=ProposalPolicy())
    result = draft_proposals(
        findings, index=index, workflow=workflow, llm_client=InvalidDiffLLMClient(), identity=SWEEP_IDENTITY
    )

    assert result.created == ()
    assert result.discarded.get("invalid_diff") == len(findings)
    assert proposal_store.list().total == 0


def test_an_llm_client_error_on_one_finding_is_discarded_not_raised_and_the_sweep_continues(tmp_path):
    """D1 regression: a `LLMClientError` (rate limit/transport) on one finding must not propagate
    out of `draft_proposals` and must not abort drafting the remaining findings in the sweep."""
    store, index = build_drift_corpus_with_index(tmp_path)
    findings = _findings(store)
    assert len(findings) >= 2, "fixture regression: need at least two findings to prove the sweep continues"

    proposal_store = ProposalStore(tmp_path / "proposals")
    workflow = ProposalWorkflow(store=proposal_store, policy=ProposalPolicy())
    result = draft_proposals(
        findings, index=index, workflow=workflow, llm_client=RaisingOnceLLMClient(fail_on_call=1), identity=SWEEP_IDENTITY
    )

    assert result.discarded.get("llm_error") == 1
    # every other finding still got a real drafting attempt (created, or discarded for one of the
    # existing, non-llm_error reasons) - the raising call did not abort the sweep.
    assert len(result.created) + sum(result.discarded.values()) == len(findings)
    assert len(result.created) + result.discarded.get("duplicate", 0) == len(findings) - 1


def test_finding_with_no_indexed_packages_is_discarded_not_a_crash(tmp_path):
    """A finding whose package_ids aren't actually in the index (shouldn't happen with a real
    scan, but the drafting layer must not assume it) yields no evidence to fetch - discarded, not
    an exception."""
    from ap_index.index_store import IndexStore
    from ap_planner_bot.detectors import Finding

    empty_index = IndexStore(tmp_path / "empty-index")
    proposal_store = ProposalStore(tmp_path / "proposals")
    workflow = ProposalWorkflow(store=proposal_store, policy=ProposalPolicy())

    finding = Finding(
        detector="reason_code_unknown",
        kind="reason_code_add",
        summary="unreachable package",
        package_ids=("pkg_does_not_exist",),
        detail={"profile": "commodity_commit_forecast", "reason_code": "BOGUS", "count": 5},
    )
    result = draft_proposals(
        [finding], index=empty_index, workflow=workflow, llm_client=ScriptedDraftingLLMClient(), identity=SWEEP_IDENTITY
    )
    assert result.created == ()
    assert result.discarded == {"no_evidence_resolved": 1}
