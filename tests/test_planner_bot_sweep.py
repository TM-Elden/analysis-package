"""`ap_planner_bot.sweep.run_sweep`: the P4.4 entry point wiring scan -> detect -> draft -> persist
into one library call, over the same seeded corpora `test_planner_bot_service.py` exercises at the
service layer directly."""

from __future__ import annotations

from _planner_bot_corpus import build_clean_corpus_with_index, build_drift_corpus_with_index
from _planner_bot_fake_llm import ScriptedDraftingLLMClient

from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_planner_bot.sweep import run_sweep
from ap_proposals.store import ProposalStore

SWEEP_IDENTITY = Identity(id="svc.planner-sweep", roles=frozenset({Role.STANDARD_APPROVER}))


def test_run_sweep_end_to_end_on_drift_corpus_creates_proposals(tmp_path):
    store, index = build_drift_corpus_with_index(tmp_path)
    proposal_store = ProposalStore(tmp_path / "proposals")

    result = run_sweep(
        store=store,
        index=index,
        proposal_store=proposal_store,
        llm_client=ScriptedDraftingLLMClient(),
        identity=SWEEP_IDENTITY,
    )

    assert result.created
    assert proposal_store.list().total == len(result.created)


def test_run_sweep_end_to_end_on_clean_corpus_creates_nothing(tmp_path):
    store, index = build_clean_corpus_with_index(tmp_path)
    proposal_store = ProposalStore(tmp_path / "proposals")

    result = run_sweep(
        store=store,
        index=index,
        proposal_store=proposal_store,
        llm_client=ScriptedDraftingLLMClient(),
        identity=SWEEP_IDENTITY,
    )

    assert result.created == ()
    assert proposal_store.list().total == 0


def test_run_sweep_is_idempotent_a_second_run_dedups(tmp_path):
    store, index = build_drift_corpus_with_index(tmp_path)
    proposal_store = ProposalStore(tmp_path / "proposals")

    first = run_sweep(
        store=store, index=index, proposal_store=proposal_store, llm_client=ScriptedDraftingLLMClient(), identity=SWEEP_IDENTITY
    )
    second = run_sweep(
        store=store, index=index, proposal_store=proposal_store, llm_client=ScriptedDraftingLLMClient(), identity=SWEEP_IDENTITY
    )

    assert first.created
    assert second.created == ()
    assert proposal_store.list().total == len(first.created)
