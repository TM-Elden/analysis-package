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
from ap_manager_bot.service import ManagerBot

from _manager_bot_corpus import build_corpus
from _manager_bot_fake_llm import ScriptedLLMClient

TEAM_READER = Identity(id="planner.fmt", roles=frozenset({Role.TEAM_READER}))


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
            lead = "This was held for a documented planning reason, not a data error."
            detail = f"Source: {top['package_id']} ({top['chunk_type']} {top['field_path']})."
            answer_input = {"answer": f"{lead}\n{detail}", "no_evidence": False, "citations": citations}
        return {
            "content": [
                {"type": "tool_use", "id": f"toolu_{next(self._ids)}", "name": "provide_answer", "input": answer_input}
            ],
            "stop_reason": "tool_use",
        }


class RunOnMultiFactLLMClient(LLMClient):
    """Plays the "before" shape the captain's screenshot flagged as a follow-up bug: a compliant
    lead sentence, then every supporting fact crammed into one semicolon/comma-joined run-on
    sentence instead of one fact per line."""

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
            lead = (
                "300 units of ACME's BBU-100 were held back for week 36 so the team could push "
                "for better Q4 pricing."
            )
            run_on = (
                "Override ovr_001 cut the forecast from 1,200 to 900 units, reason code "
                "HOLD_FOR_PRICE_NEGOTIATION, citing the ACME LTA-2024 contract section 4.2; this "
                f"shows up as exception ex_001 in the outputs (source: {top['package_id']})."
            )
            answer_input = {"answer": f"{lead}\n{run_on}", "no_evidence": False, "citations": citations}
        return {
            "content": [
                {"type": "tool_use", "id": f"toolu_{next(self._ids)}", "name": "provide_answer", "input": answer_input}
            ],
            "stop_reason": "tool_use",
        }


class MultiFactPerLineLLMClient(LLMClient):
    """Plays the "after" shape this follow-up task asks for: lead sentence, then one distinct
    supporting fact per dash-prefixed line - not a single semicolon/comma-joined sentence."""

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
            lead = (
                "300 units of ACME's BBU-100 were held back for week 36 so the team could push "
                "for better Q4 pricing."
            )
            lines = [
                "- Override ovr_001 cut the forecast from 1,200 to 900 units.",
                "- Reason code: HOLD_FOR_PRICE_NEGOTIATION.",
                "- Citation: ACME LTA-2024 contract section 4.2.",
                f"- Exception: ex_001 (source: {top['package_id']}).",
            ]
            answer_input = {
                "answer": lead + "\n" + "\n".join(lines),
                "no_evidence": False,
                "citations": citations,
            }
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


def test_multi_fact_run_on_vs_one_fact_per_line(corpus):
    """Follow-up captain feedback: the lead sentence works, but everything after it was still one
    dense semicolon/comma-joined run-on sentence cramming several distinct facts together. Uses
    the actual captain example (override, reason code, citation, exception id) as the scenario."""
    question = "Why did we hold quantity for ACME BBU-100?"

    run_on = ManagerBot(index=corpus.index, store=corpus.store, llm_client=RunOnMultiFactLLMClient())
    run_on_answer = run_on.answer(question, identity=TEAM_READER)
    assert not run_on_answer.refused
    run_on_lines = run_on_answer.answer.split("\n")
    # "before": lead sentence is fine, but everything else is one line with every fact stacked in.
    assert len(run_on_lines) == 2
    assert "; " in run_on_lines[1] and ", " in run_on_lines[1]

    per_line = ManagerBot(index=corpus.index, store=corpus.store, llm_client=MultiFactPerLineLLMClient())
    per_line_answer = per_line.answer(question, identity=TEAM_READER)
    assert not per_line_answer.refused
    lines = per_line_answer.answer.split("\n")
    lead, fact_lines = lines[0], lines[1:]
    # "after": lead sentence, then one distinct supporting fact per line - not a single run-on.
    assert "held back" in lead
    assert len(fact_lines) >= 4, "each distinct fact (override, reason code, citation, exception) gets its own line"
    for fact_line in fact_lines:
        assert fact_line.startswith("- ")
        assert "; " not in fact_line  # no fact line itself bundles multiple facts via semicolons
    joined = " ".join(fact_lines)
    assert "ovr_001" in joined
    assert "HOLD_FOR_PRICE_NEGOTIATION" in joined
    assert "LTA-2024" in joined
    assert "ex_001" in joined
    assert per_line_answer.citations, "formatting change must not weaken the citation contract"
