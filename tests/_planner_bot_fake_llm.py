"""Deterministic `LLMClient` test doubles for `ap_planner_bot.service`'s single-turn drafting
call - mirrors `_manager_bot_fake_llm.py::ScriptedLLMClient`'s role: exercise the real
schema-validation + evidence-resolution + dedup harness end to end without a network call, not
model judgment.

`service.py` embeds the finding's `kind` and `detail` (JSON) plus every `ref_id`/`package_id`
evidence pair it fetched into one plain-text user turn (`_finding_prompt`) - these fakes parse that
same text back out, exactly the way a real model reads it from the prompt.
"""

from __future__ import annotations

import itertools
import json
import re
from typing import Any

from ap_manager_bot.llm_client import LLMClient

_KIND_RE = re.compile(r"kind='(\w+)'")
_DETAIL_RE = re.compile(r"^Detail: (.*)$", re.MULTILINE)
_REF_RE = re.compile(r"^- ref_id=(\S+) package_id=(\S+)$", re.MULTILINE)


def _parse_prompt(prompt: str) -> tuple[str, dict, list[tuple[str, str]]]:
    kind_match = _KIND_RE.search(prompt)
    detail_match = _DETAIL_RE.search(prompt)
    kind = kind_match.group(1) if kind_match else ""
    detail = json.loads(detail_match.group(1)) if detail_match else {}
    refs = _REF_RE.findall(prompt)
    return kind, detail, refs


def _decline() -> dict[str, Any]:
    return {"content": [], "stop_reason": "end_turn"}


def _tool_use(tool_id: str, name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}], "stop_reason": "tool_use"}


def _mechanical_diff(kind: str, detail: dict[str, Any]) -> dict[str, Any] | None:
    """The one mechanically-obvious diff each drift scenario's finding implies - a fake stands in
    for a model's judgment here, not for the enforcement layer (`service.py` still validates and
    resolves whatever this returns)."""
    if kind == "reason_code_add":
        return {
            "profile": detail.get("profile", ""),
            "code": detail.get("reason_code", ""),
            "description": f"Add reason code {detail.get('reason_code')!r} (seen {detail.get('count')} time(s))",
        }
    if kind == "profile_change":
        if detail.get("check_id"):
            return {
                "profile": "commodity_commit_forecast",
                "file": "training_grade.json",
                "before": None,
                "after": {"tune_check": detail["check_id"]},
            }
        if detail.get("field_path"):
            return {
                "profile": "commodity_commit_forecast",
                "file": "field_path_grammar.json",
                "before": None,
                "after": {"allow_field_path": detail["field_path"]},
            }
        if detail.get("declared_versions"):
            return {
                "profile": detail.get("profile", ""),
                "file": "reason_codes.json",
                "before": None,
                "after": {"profile_version": detail["declared_versions"][0]},
            }
    return None


class ScriptedDraftingLLMClient(LLMClient):
    """Drafts a mechanically-correct proposal for every finding it's shown, citing every ref_id it
    was given - the "happy path" fake used by the eval/dedup tests."""

    def __init__(self) -> None:
        self._ids = itertools.count(1)

    def complete(self, *, system: str, messages: list[dict], tools: list[dict]) -> dict:
        del system, tools
        prompt = messages[-1]["content"][0]["text"]
        kind, detail, refs = _parse_prompt(prompt)
        diff = _mechanical_diff(kind, detail)
        if diff is None or not refs:
            return _decline()

        draft_input = {
            "kind": kind,
            "summary": f"Drafted from a {kind} finding",
            "rationale": "Deterministic drift signal from the corpus scan (see finding detail).",
            "diff": diff,
            "evidence": [{"ref_id": ref_id} for ref_id, _package_id in refs],
        }
        return _tool_use(f"toolu_{next(self._ids)}", "draft_proposal", draft_input)


class InventedEvidenceLLMClient(LLMClient):
    """Otherwise-valid draft, but every evidence ref_id is fabricated - none should resolve, so the
    whole draft must be discarded (`no_evidence_resolved`), not partially trusted."""

    def __init__(self) -> None:
        self._ids = itertools.count(1)

    def complete(self, *, system: str, messages: list[dict], tools: list[dict]) -> dict:
        del system, tools
        prompt = messages[-1]["content"][0]["text"]
        kind, detail, _refs = _parse_prompt(prompt)
        diff = _mechanical_diff(kind, detail)
        if diff is None:
            return _decline()
        draft_input = {
            "kind": kind,
            "summary": "Drafted from a fabricated ref_id",
            "rationale": "This evidence was never shown to the model.",
            "diff": diff,
            "evidence": [{"ref_id": "chunk_does_not_exist_12345"}],
        }
        return _tool_use(f"toolu_{next(self._ids)}", "draft_proposal", draft_input)


class InvalidDiffLLMClient(LLMClient):
    """Otherwise-valid draft, but the diff is missing required fields for its own declared kind -
    must be discarded (`invalid_diff`), never "fixed up" or stored raw."""

    def __init__(self) -> None:
        self._ids = itertools.count(1)

    def complete(self, *, system: str, messages: list[dict], tools: list[dict]) -> dict:
        del system, tools
        prompt = messages[-1]["content"][0]["text"]
        kind, _detail, refs = _parse_prompt(prompt)
        if not kind or not refs:
            return _decline()
        draft_input = {
            "kind": kind,
            "summary": "Drafted with a malformed diff",
            "rationale": "Missing required fields for this kind on purpose.",
            "diff": {"not_a_real_field": "x"},
            "evidence": [{"ref_id": ref_id} for ref_id, _package_id in refs],
        }
        return _tool_use(f"toolu_{next(self._ids)}", "draft_proposal", draft_input)
