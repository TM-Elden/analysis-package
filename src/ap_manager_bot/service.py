"""`ManagerBot.answer`: the C4 tool-using loop (report section 5.3 - "tool-using loop, not
embed-and-stuff RAG"). The LLM composes its own `search_packages` / `get_package_summary` /
`get_gate_report` calls across turns, then must close with `provide_answer` - there is no other way
out of the loop, which is what makes the citation contract enforceable server-side rather than a
prompt-only request: `provide_answer`'s `citations[].ref_id` values are checked against
`ManagerBotTools.resolve_citation` (see tool_backend.py), so a citation the model invents, or that
points at a chunk the post-search scope check dropped, is silently discarded rather than shipped -
if every citation on an answer turns out fake, the whole answer is downgraded to a refusal. This is
the enforcement backstop; `_SYSTEM_PROMPT` asking nicely is not the contract.
"""

from __future__ import annotations

import json

from ap_auth.identity import Identity
from ap_index.index_store import IndexStore
from ap_manager_bot.llm_client import LLMClient
from ap_manager_bot.models import ChatAnswer, Citation
from ap_manager_bot.tool_backend import TOOL_SCHEMAS, ManagerBotTools
from ap_store.store import PackageStore

NO_EVIDENCE_ANSWER = "No evidence found in the packages you have access to for this question."

_SYSTEM_PROMPT = """You are fathm's manager bot, answering questions about a team's Analysis \
Package corpus. You only know what search_packages / get_package_summary / get_gate_report return \
in this conversation - you have no other knowledge of this team's packages, and must not use \
general knowledge to fill gaps.

Rules:
- Compose your own searches; call tools more than once if the first query does not surface enough.
- Every claim in your final answer must be traceable to a specific ref_id you retrieved this turn.
- If nothing retrieved actually answers the question, call provide_answer with no_evidence=true and \
an empty citations list - do not guess or answer from outside knowledge.
- Finish by calling provide_answer exactly once. That is the only way to end the conversation."""

_MAX_TURNS = 6


def _anthropic_tools() -> list[dict]:
    return [{"name": name, **schema} for name, schema in TOOL_SCHEMAS.items()]


class ManagerBot:
    def __init__(self, *, index: IndexStore, store: PackageStore, llm_client: LLMClient, max_turns: int = _MAX_TURNS):
        self._index = index
        self._store = store
        self._llm_client = llm_client
        self._max_turns = max_turns

    def answer(self, question: str, *, identity: Identity) -> ChatAnswer:
        tools = ManagerBotTools(index=self._index, store=self._store, identity=identity)
        messages: list[dict] = [{"role": "user", "content": [{"type": "text", "text": question}]}]
        tool_schemas = _anthropic_tools()

        for turn in range(1, self._max_turns + 1):
            response = self._llm_client.complete(system=_SYSTEM_PROMPT, messages=messages, tools=tool_schemas)
            content = response.get("content") or []
            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if not tool_uses:
                # The model ended the turn without calling provide_answer - fail closed rather than
                # ship whatever free-text content it produced uncited.
                return ChatAnswer(answer=NO_EVIDENCE_ANSWER, refused=True, turns=turn)

            messages.append({"role": "assistant", "content": content})
            final = self._final_answer(tool_uses, tools, turn)
            if final is not None:
                return final

            tool_results = [self._run_tool(block, tools) for block in tool_uses]
            messages.append({"role": "user", "content": tool_results})

        return ChatAnswer(answer=NO_EVIDENCE_ANSWER, refused=True, turns=self._max_turns)

    # -- internals --------------------------------------------------------

    @staticmethod
    def _run_tool(block: dict, tools: ManagerBotTools) -> dict:
        name, tool_input, tool_use_id = block.get("name"), block.get("input") or {}, block["id"]
        handler = {
            "search_packages": tools.search_packages,
            "get_package_summary": tools.get_package_summary,
            "get_gate_report": tools.get_gate_report,
        }.get(name)
        if handler is None:
            result = {"error": f"unknown tool: {name}"}
        else:
            try:
                result = handler(**tool_input)
            except TypeError as exc:
                result = {"error": f"bad input for {name}: {exc}"}
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": _to_text(result)}

    @staticmethod
    def _final_answer(tool_uses: list[dict], tools: ManagerBotTools, turn: int) -> ChatAnswer | None:
        provide_answer_calls = [b for b in tool_uses if b.get("name") == "provide_answer"]
        if not provide_answer_calls:
            return None
        tool_input = provide_answer_calls[0].get("input") or {}
        no_evidence = bool(tool_input.get("no_evidence"))
        resolved: list[Citation] = []
        for raw in tool_input.get("citations") or []:
            ref_id = raw.get("ref_id") if isinstance(raw, dict) else None
            citation = tools.resolve_citation(ref_id) if ref_id else None
            if citation is not None:
                resolved.append(citation)

        if no_evidence or not resolved:
            return ChatAnswer(answer=NO_EVIDENCE_ANSWER, refused=True, turns=turn)

        answer_text = str(tool_input.get("answer") or "").strip()
        if not answer_text:
            return ChatAnswer(answer=NO_EVIDENCE_ANSWER, refused=True, turns=turn)
        return ChatAnswer(answer=answer_text, citations=tuple(resolved), refused=False, turns=turn)


def _to_text(result: dict) -> str:
    return json.dumps(result)
