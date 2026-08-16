"""Per-kind `diff_json` shape validation (C6/C7).

Each of the four proposal kinds gets its own minimal JSON Schema for `diff_json` - just enough
structure for this storage/workflow layer to reject a malformed diff at creation time. These are
deliberately stubs: the real shapes belong to the drafting bot (a separate task, per
`data/fathm-phase4-readiness/report.md` §5.3/§5.5 in the firstmate repo) and to the apply mechanism
(§5.5, also separate) once it exists. Validation reuses the same `jsonschema` pattern as
`ap_mcp.errors.validate_arguments` - one source of truth, planner-serving messages - rather than a
parallel hand-rolled shape check.
"""

from __future__ import annotations

from typing import Any

import jsonschema

#: kind -> JSON Schema for that kind's `diff_json` (and, when present, `edited_diff_json`).
#: Deliberately minimal/stub shapes - see module docstring.
DIFF_SCHEMAS: dict[str, dict[str, Any]] = {
    "standard_change": {
        "type": "object",
        "required": ["target", "description"],
        "properties": {
            "target": {"type": "string", "minLength": 1, "description": "path within standard/ this change touches"},
            "description": {"type": "string", "minLength": 1},
            "patch": {"type": "string", "description": "optional draft patch text, exported at approve-time (see CLAUDE.md's ap_proposals section)"},
        },
    },
    "profile_change": {
        "type": "object",
        "required": ["profile", "file", "after"],
        "properties": {
            "profile": {"type": "string", "minLength": 1, "description": "profile name under profiles/<name>/"},
            "file": {"type": "string", "minLength": 1, "description": "relative path within the profile, e.g. reason_codes.json"},
            "before": {"description": "current file contents (JSON), or null if the file doesn't exist yet"},
            "after": {"description": "proposed file contents (JSON)"},
        },
    },
    "reason_code_add": {
        "type": "object",
        "required": ["profile", "code", "description"],
        "properties": {
            "profile": {"type": "string", "minLength": 1},
            "code": {"type": "string", "minLength": 1},
            "description": {"type": "string", "minLength": 1},
        },
    },
    "check_add": {
        "type": "object",
        "required": ["check_id", "severity", "description"],
        "properties": {
            "check_id": {"type": "string", "minLength": 1},
            "severity": {"type": "string", "enum": ["required", "advisory"]},
            "description": {"type": "string", "minLength": 1},
        },
    },
}

KINDS: frozenset[str] = frozenset(DIFF_SCHEMAS)


class ProposalValidationError(Exception):
    """Raised when `kind` is unknown or `diff_json` fails that kind's schema. `field_messages` is
    one planner-serving line per violation, mirroring `ap_mcp.errors.ToolValidationError`."""

    def __init__(self, kind: str, field_messages: list[str]) -> None:
        self.kind = kind
        self.field_messages = field_messages
        header = f"proposal kind {kind!r}: diff rejected -"
        body = "; ".join(field_messages)
        super().__init__(f"{header} {body}")


def validate_diff(kind: str, diff: dict[str, Any]) -> None:
    """Validate `diff` against `kind`'s schema. Raises ProposalValidationError on an unknown kind
    or a schema violation."""
    if kind not in DIFF_SCHEMAS:
        raise ProposalValidationError(kind, [f"unknown kind - must be one of: {', '.join(sorted(KINDS))}"])
    validator = jsonschema.Draft202012Validator(DIFF_SCHEMAS[kind])
    errors = sorted(validator.iter_errors(diff), key=lambda e: list(e.path))
    if not errors:
        return
    messages = [f"{'.'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors]
    raise ProposalValidationError(kind, messages)
