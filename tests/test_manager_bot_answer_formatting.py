"""Answer-formatting guidance for the C4 manager bot's `_SYSTEM_PROMPT` (captain feedback: a real
screenshot showed a dense, citation-woven paragraph that's hard to scan on a phone).

This is a prompt-only change - no template/rendering code was touched (the console's `.chat-answer`
CSS already has `white-space: pre-wrap`, so a real newline in `answer` renders as a line break
today). `ScriptedLLMClient` ignores `system` entirely (see its docstring - it exercises the
harness, not model judgment), so it can't demonstrate the prompt itself changing model output;
what it *can* demonstrate is that the harness (citation resolution, the no-evidence refusal path)
is indifferent to which of the two shapes - the old dense one-liner, or the new lead-sentence-then-
detail shape the prompt now asks for - the answer text takes. `FormattedScriptedLLMClient` below
plays the "after" shape a compliant model would now produce.
"""

from __future__ import annotations

import itertools
import json
import re

import pytest

from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_manager_bot.llm_client import LLMClient
from ap_manager_bot.service import _SYSTEM_PROMPT, ManagerBot

from _manager_bot_corpus import build_corpus
from _manager_bot_fake_llm import ScriptedLLMClient

TEAM_READER = Identity(id="planner.fmt", roles=frozenset({Role.TEAM_READER}))


def test_system_prompt_documents_lead_sentence_then_detail_shape():
    lower = _SYSTEM_PROMPT.lower()
    assert "line break" in lower
    assert "plain-language" in lower
    # still the same enforcement contract - formatting guidance must not weaken it.
    assert "ref_id" in lower
    assert "no_evidence" in lower


_ENTITY = re.compile(r"[A-Z][A-Z0-9-]{2,}")


class FormattedScriptedLLMClient(LLMClient):
    """Plays the "after" shape: a plain-language lead sentence, a real newline, then supporting
    detail (ids, field path) - what a model following the new formatting rules would produce."""

    def __init__(self) -> None:
        self._ids = itertools.count(1)

    def complete(self, *, system: str, messages: list[dict], tools: list[dict]) -> dict:
        del system, tools
        last = messages[-1]
        if last["role"] == "user" and last["content"] and last["content"][0].get("type") == "text":
            question = last["content"][0]["text"]
            entities = _ENTITY.findall(question)
            query = " ".join(entities) if entities else question
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"toolu_{next(self._ids)}",
                        "name": "search_packages",
                        "input": {"query": query, "limit": 5},
                    }
                ],
                "stop_reason": "tool_use",
            }
        block = last["content"][0]
        payload = json.loads(block["content"])
        results = payload.get("results") or []
        if not results:
            answer_input = {"answer": "", "no_evidence": True, "citations": []}
        else:
            top = results[0]
            citations = [{"ref_id": top["ref_id"]}]
            lead = f"This was held for a documented planning reason, not a data error."
            detail = f"Source: {top['package_id']} ({top['chunk_type']} {top['field_path']})."
            answer_input = {"answer": f"{lead}\n{detail}", "no_evidence": False, "citations": citations}
        return {
            "content": [
                {"type": "tool_use", "id": f"toolu_{next(self._ids)}", "name": "provide_answer", "input": answer_input}
            ],
            "stop_reason": "tool_use",
        }


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("manager-bot-formatting-corpus")
    c = build_corpus(tmp_path)
    yield c
    c.store.close()
    c.index.close()


def test_before_after_answer_shape_changes_while_contract_holds(corpus):
    question = "Why did we hold quantity for ACME BBU-100?"

    dense = ManagerBot(index=corpus.index, store=corpus.store, llm_client=ScriptedLLMClient())
    dense_answer = dense.answer(question, identity=TEAM_READER)
    assert not dense_answer.refused
    # "before": ids/codes are woven straight into the lead sentence's own grammar
    # ("From package pkg_...(override field): ..."), not set apart on their own line.
    dense_lead = dense_answer.answer.split("\n", 1)[0]
    assert "From package" in dense_lead

    formatted = ManagerBot(index=corpus.index, store=corpus.store, llm_client=FormattedScriptedLLMClient())
    formatted_answer = formatted.answer(question, identity=TEAM_READER)
    assert not formatted_answer.refused
    # "after": a plain-language lead sentence, then a real line break, then supporting detail
    # (ids, field path) - not woven into the lead sentence.
    assert "\n" in formatted_answer.answer
    lead, _, detail = formatted_answer.answer.partition("\n")
    assert lead and detail
    assert "pkg_" not in lead
    assert "pkg_" in detail
    assert formatted_answer.citations, "formatting change must not weaken the citation contract"
