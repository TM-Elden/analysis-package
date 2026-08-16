"""A deterministic `LLMClient` test double that drives the exact same tool-loop protocol
(`ap_manager_bot.service.ManagerBot`) a real model would, without any network call.

Production talks to a captain-approved frontier-model API (`ap_manager_bot.llm_client.AnthropicHTTPClient`
- see that module's docstring for the egress-posture decision). What the eval/unit tests below need
to exercise is the *harness*: retrieval, the pre+post scoping double-check, and the citation
contract (a citation must trace to something actually retrieved this conversation, and an empty
retrieval must refuse) - none of that depends on which model is composing queries. `ScriptedLLMClient`
plays the model's role with a fixed, inspectable strategy (extract entity-looking tokens from the
question, search, cite the top hit or refuse) so those eval assertions are about the real
retrieval+scoping+citation pipeline end to end, not about the fake's own logic.
"""

from __future__ import annotations

import itertools
import json
import re

from ap_manager_bot.llm_client import LLMClient

#: fathm queries are entity-heavy (report section 5.3) - part numbers and supplier names read as
#: runs of uppercase letters/digits/hyphens. A real model composes a search query the same way for
#: the same reason (exact-term BM25 over this corpus beats a bag-of-words query); this regex is that
#: same heuristic, not a shortcut unique to the fake.
_ENTITY = re.compile(r"[A-Z][A-Z0-9-]{2,}")


class ScriptedLLMClient(LLMClient):
    def __init__(self) -> None:
        self._ids = itertools.count(1)

    def complete(self, *, system: str, messages: list[dict], tools: list[dict]) -> dict:
        del system, tools
        last = messages[-1]
        if last["role"] == "user" and last["content"] and last["content"][0].get("type") == "text":
            question = last["content"][0]["text"]
            return self._search_turn(question)
        return self._answer_turn(last)

    def _search_turn(self, question: str) -> dict:
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

    def _answer_turn(self, tool_result_message: dict) -> dict:
        block = tool_result_message["content"][0]
        payload = json.loads(block["content"])
        results = payload.get("results") or []

        if not results:
            answer_input = {"answer": "", "no_evidence": True, "citations": []}
        else:
            top = results[0]
            citations = [{"ref_id": r["ref_id"]} for r in results[:2] if r["package_id"] == top["package_id"]]
            answer_input = {
                "answer": f"From package {top['package_id']} ({top['chunk_type']} {top['field_path']}): {top['text'][:200]}",
                "no_evidence": False,
                "citations": citations,
            }

        return {
            "content": [
                {"type": "tool_use", "id": f"toolu_{next(self._ids)}", "name": "provide_answer", "input": answer_input}
            ],
            "stop_reason": "tool_use",
        }
