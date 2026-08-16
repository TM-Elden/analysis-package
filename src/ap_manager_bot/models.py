"""Read-model dataclasses for the manager bot's answer contract."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Citation:
    """One grounded reference - C4's required citation shape: package id + row/field id.

    `ref_id` is the id the tool loop used to point at this evidence (an `ap_index` chunk_id for
    `search_packages`/`get_package_summary` results, or a synthesized `"<package_id>:gate"` id for
    `get_gate_report`) - kept so `service.py` can verify a citation traces back to something this
    conversation actually retrieved, not something the model invented.
    """

    ref_id: str
    package_id: str
    package_version: str
    field_path: str
    chunk_type: str


@dataclass(frozen=True)
class ChatAnswer:
    """The manager bot's response to one question."""

    answer: str
    citations: tuple[Citation, ...] = ()
    refused: bool = False
    #: Number of LLM turns the tool loop took - surfaced for observability/eval, not part of the
    #: citation contract.
    turns: int = 0


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation the LLM asked for."""

    tool_use_id: str
    name: str
    input: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LLMTurn:
    """One `LLMClient.complete(...)` response: either the model wants to call tools, or it is done
    (in which case the tool loop expects the final call to have been `provide_answer` - see
    `service.py::_SYSTEM_PROMPT`)."""

    tool_calls: tuple[ToolCall, ...]
    stop_reason: str
