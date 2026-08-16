"""C4 scoping acceptance test (task brief: "a caller without access to a confidential package's
team gets no content from it, even when the query would otherwise surface it") plus harness-level
unit tests for the citation contract (hallucinated/dropped citations, refusal on empty retrieval,
and the post-search re-check dropping an out-of-scope chunk) that don't need the full eval corpus.
"""

from __future__ import annotations

from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_index.models import ChunkRecord
from ap_manager_bot.scoping import chunk_in_scope, confidentiality_filter_for
from ap_manager_bot.service import NO_EVIDENCE_ANSWER, ManagerBot

from _manager_bot_corpus import build_corpus
from _manager_bot_fake_llm import ScriptedLLMClient

TEAM_READER = Identity(id="planner.scope", roles=frozenset({Role.TEAM_READER}))
ANALYST = Identity(id="lead.scope", roles=frozenset({Role.ANALYST}))
ADMIN = Identity(id="admin.scope", roles=frozenset({Role.ADMIN}))


def test_confidentiality_filter_base_vs_elevated_roles():
    assert confidentiality_filter_for(TEAM_READER) == ("internal",)
    assert confidentiality_filter_for(ANALYST) == ("internal", "internal_restricted")
    assert confidentiality_filter_for(ADMIN) == ("internal", "internal_restricted")  # admin bypass


def test_chunk_in_scope_post_check():
    restricted = ChunkRecord(
        chunk_id="c1", package_id="p", package_version="1.0.0", as_of="2026-01-01",
        profile="commodity_commit_forecast/0.1", chunk_type="override", field_path="x",
        confidentiality="internal_restricted", text="t",
    )
    assert not chunk_in_scope(TEAM_READER, restricted)
    assert chunk_in_scope(ANALYST, restricted)


def test_team_reader_gets_no_content_from_a_confidential_package_even_when_query_would_surface_it(tmp_path):
    corpus = build_corpus(tmp_path)
    try:
        confidential_id = corpus.package_ids["vaulttec_relay"]

        bot = ManagerBot(index=corpus.index, store=corpus.store, llm_client=ScriptedLLMClient())
        answer = bot.answer("What supplier risk split change applies to VAULT-TEC RELAY-99?", identity=TEAM_READER)

        # The query terms are real (they're in the confidential package) - if scoping were broken,
        # this would come back cited. Instead it must refuse, and *no* citation may point at the
        # restricted package regardless.
        assert not any(c.package_id == confidential_id for c in answer.citations)
        assert answer.refused is True
        assert answer.answer == NO_EVIDENCE_ANSWER

        # The same question, same corpus, for a caller who *does* hold an elevated role: real content.
        analyst_answer = bot.answer(
            "What supplier risk split change applies to VAULT-TEC RELAY-99?", identity=ANALYST
        )
        assert not analyst_answer.refused
        assert any(c.package_id == confidential_id for c in analyst_answer.citations)
    finally:
        corpus.store.close()
        corpus.index.close()


class _EmptyResultsClient:
    """Always searches, always gets nothing back - the model itself never even calls
    provide_answer(no_evidence=False) here; used to confirm the loop's own fail-closed branch when
    the model just stops without ending via provide_answer."""

    def complete(self, *, system, messages, tools):
        del system, tools
        if len(messages) == 1:
            return {
                "content": [{"type": "tool_use", "id": "t1", "name": "search_packages", "input": {"query": "nothing"}}],
                "stop_reason": "tool_use",
            }
        # Model stops without calling provide_answer at all.
        return {"content": [{"type": "text", "text": "I dunno"}], "stop_reason": "end_turn"}


def test_model_ending_without_provide_answer_is_treated_as_a_refusal(tmp_path):
    corpus = build_corpus(tmp_path)
    try:
        bot = ManagerBot(index=corpus.index, store=corpus.store, llm_client=_EmptyResultsClient())
        answer = bot.answer("anything", identity=TEAM_READER)
        assert answer.refused is True
        assert answer.citations == ()
    finally:
        corpus.store.close()
        corpus.index.close()


class _HallucinatedCitationClient:
    """Calls provide_answer with a citation ref_id that was never returned by any tool call this
    conversation - must be dropped, and since it's the only citation, the answer must downgrade to
    a refusal rather than ship an uncited claim."""

    def complete(self, *, system, messages, tools):
        del system, tools
        if len(messages) == 1:
            return {
                "content": [{"type": "tool_use", "id": "t1", "name": "search_packages", "input": {"query": "ACME"}}],
                "stop_reason": "tool_use",
            }
        return {
            "content": [
                {
                    "type": "tool_use",
                    "id": "t2",
                    "name": "provide_answer",
                    "input": {
                        "answer": "ACME held units for price talks.",
                        "no_evidence": False,
                        "citations": [{"ref_id": "made-up-chunk-id-never-returned"}],
                    },
                }
            ],
            "stop_reason": "tool_use",
        }


def test_hallucinated_citation_is_rejected_and_answer_downgrades_to_refusal(tmp_path):
    corpus = build_corpus(tmp_path)
    try:
        bot = ManagerBot(index=corpus.index, store=corpus.store, llm_client=_HallucinatedCitationClient())
        answer = bot.answer("Why did we hold ACME BBU-100?", identity=TEAM_READER)
        assert answer.refused is True
        assert answer.citations == ()
        assert answer.answer == NO_EVIDENCE_ANSWER
    finally:
        corpus.store.close()
        corpus.index.close()
