"""Planner-serving tool errors - the MCP-layer analogue of ap_gate's `evidence[]` layer.

A rejected tool call should read like gate evidence: which field, what's wrong, how to fix it,
phrased for "now, while the reasoning is still in your context" (design report §6) - not a bare
jsonschema stack trace.
"""

from __future__ import annotations

import jsonschema


class ToolValidationError(Exception):
    """Raised when a tool call's arguments fail schema validation. `message` is the full
    planner-facing text; `field_messages` is the same content split one-per-offending-field, for
    callers (like the MCP server) that want to render a structured list instead of one string."""

    def __init__(self, tool_name: str, field_messages: list[str]) -> None:
        self.tool_name = tool_name
        self.field_messages = field_messages
        header = f"{tool_name}: call rejected - fix and retry now, while the reasoning is still in your context:"
        body = "\n".join(f"  - {m}" for m in field_messages)
        super().__init__(f"{header}\n{body}")


def _field_path(error: jsonschema.exceptions.ValidationError) -> str:
    if not error.path:
        return "(root)"
    parts: list[str] = []
    for segment in error.path:
        parts.append(f"[{segment}]" if isinstance(segment, int) else (f".{segment}" if parts else str(segment)))
    return "".join(parts)


def validate_arguments(tool_name: str, arguments: dict, input_schema: dict) -> None:
    """Validate `arguments` against `input_schema` - the exact schema object advertised in
    TOOL_SCHEMAS / tools/list, so server-side validation cannot drift from what the client was
    told (the documented MCP schema/enforcement drift bug class - design report §3.2, §6).
    Raises ToolValidationError with one planner-serving line per violation."""
    validator = jsonschema.Draft202012Validator(input_schema)
    errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.path))
    if not errors:
        return

    messages: list[str] = []
    for error in errors:
        field = _field_path(error)
        if error.validator == "required":
            # jsonschema's "required" errors report the missing property name in the message,
            # not error.path (path is the object *containing* the missing key) - surface it plainly.
            messages.append(f"{field}: {error.message} - this tool call must include it, it cannot be added later")
        else:
            messages.append(f"{field}: {error.message}")
    raise ToolValidationError(tool_name, messages)
