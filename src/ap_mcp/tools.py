"""fathm-ap MCP tool implementations: package_create, package_check, package_finalize,
override_record.

Thin layer, per the design report (`data/fathm-contract-enforcement-research/report.md` §6 in the
firstmate repo): every tool here calls the exact same library functions the rest of the codebase
uses - `ap_agent_tools.tools` for create/check/publish, `ap_gate.load_manifest` /
`ap_gate.checks.pathsafe` / `ap_gate.schema` for the override row. Nothing here re-implements gate
or manifest logic.

`override_record` is the P4-critical tool (design report §6 item 2): `draft_reason_text` is a
required schema parameter, so a call cannot structurally omit the agent's draft rationale - the
call *is* the capture. The written row carries `agent_draft: {reason_code, reason_text}` (the
draft, exactly as submitted) plus top-level `reason_code`/`reason_text`/`author` seeded from the
same call, so the row is immediately schema-valid and capture never depends on a human accepting it
later; a subsequent human edit (existing C10 review flow, out of scope here) can change the
top-level fields while `agent_draft` stays untouched as the historical record.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

from ap_agent_tools.tools import TOOL_SCHEMAS as _AGENT_TOOL_SCHEMAS
from ap_agent_tools.tools import package_check as _agent_package_check
from ap_agent_tools.tools import package_create as _agent_package_create
from ap_agent_tools.tools import package_publish as _agent_package_publish
from ap_auth.identity import Identity, parse_roles
from ap_gate.checks.pathsafe import resolve_contained
from ap_gate.load_manifest import load_manifest
from ap_gate.schema import error_field_path, load_override_row_schema, validate_instance
from ap_mcp.errors import ToolValidationError, validate_arguments

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "package_create": _AGENT_TOOL_SCHEMAS["package.create"],
    "package_check": _AGENT_TOOL_SCHEMAS["package.check"],
    "package_finalize": {
        "description": (
            "Finalize a package: publish it to the package store as an immutable "
            "package_version (ap_store.PackageStore, the same function `ap-agent-tools` and "
            "`ap-api` use). Does not require the gate to pass first - gate status is recorded on "
            "the store record; call package_check first if you need to know it will pass review."
        ),
        "input_schema": _AGENT_TOOL_SCHEMAS["package.publish"]["input_schema"],
    },
    "override_record": {
        "description": (
            "Record a planner override on labels/overrides.jsonl - the ONLY sanctioned way to "
            "write an override row (never write the JSONL file by hand: see the fathm-planning "
            "skill). Requires draft_reason_text: your own one-to-few-sentence rationale for this "
            "override, captured now while it is still in your context. This call structurally "
            "cannot omit it - that is the point. A human reviewer may later edit the row's "
            "reason_code/reason_text/author; your draft is preserved unchanged in agent_draft "
            "either way, so the capture does not depend on their accepting it."
        ),
        "input_schema": {
            "type": "object",
            "required": ["package_dir", "field_path", "before", "after", "reason_code", "draft_reason_text"],
            "properties": {
                "package_dir": {"type": "string", "description": "Path to the package whose labels.overrides_path this appends to"},
                "field_path": {"type": "string", "minLength": 1, "description": "Dotted path of the overridden output field, e.g. supplier_forecast.ACME.BBU-100.week_36_qty"},
                "before": {"description": "Value before the override (any JSON type)"},
                "after": {"description": "Value after the override (any JSON type)"},
                "reason_code": {"type": "string", "minLength": 1, "description": "Reason code for the row as recorded (defaults the human-facing top-level reason; a reviewer may later change it)"},
                "draft_reason_text": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "Your rationale for this override, in your own words, right now - one to a "
                        "few sentences. Recorded verbatim into agent_draft.reason_text and never "
                        "overwritten by a later human edit."
                    ),
                },
                "draft_reason_code": {"type": "string", "minLength": 1, "description": "Defaults to reason_code if omitted - set this only if your draft used a different code than the row's final reason_code"},
                "reason_text": {"type": "string", "description": "Human-facing top-level reason_text; defaults to draft_reason_text if omitted"},
                "author": {"type": "string", "minLength": 1, "description": "Row author; defaults to 'agent:<override_id>' pending human acceptance"},
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
                "bucket": {"type": "integer"},
                "override_id": {"type": "string", "minLength": 1, "description": "Defaults to a fresh generated id"},
            },
        },
    },
}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def package_create(**kwargs: Any) -> Path:
    validate_arguments("package_create", kwargs, TOOL_SCHEMAS["package_create"]["input_schema"])
    return _agent_package_create(kwargs.pop("dest_dir"), **kwargs)


def package_check(**kwargs: Any) -> dict[str, Any]:
    validate_arguments("package_check", kwargs, TOOL_SCHEMAS["package_check"]["input_schema"])
    return _agent_package_check(kwargs["package_dir"])


def package_finalize(**kwargs: Any) -> dict[str, Any]:
    validate_arguments("package_finalize", kwargs, TOOL_SCHEMAS["package_finalize"]["input_schema"])
    actor = Identity(id=kwargs["actor_id"], roles=parse_roles(kwargs["actor_roles"]))
    record = _agent_package_publish(kwargs["package_dir"], store_root=kwargs["store_root"], actor=actor)
    return {
        "package_id": record.package_id,
        "package_version": record.package_version,
        "status": record.status,
        "gate_overall": record.gate_overall,
    }


def override_record(**kwargs: Any) -> dict[str, Any]:
    """Append one row to the package's labels/overrides.jsonl, with `agent_draft` populated from
    `draft_reason_code`/`draft_reason_text`. Returns the written row."""
    validate_arguments("override_record", kwargs, TOOL_SCHEMAS["override_record"]["input_schema"])

    package_dir = Path(kwargs["package_dir"])
    manifest = load_manifest(package_dir)
    overrides_path = (manifest.get("labels") or {}).get("overrides_path")
    if not overrides_path:
        raise ToolValidationError(
            "override_record",
            ["package_dir: MANIFEST.yaml has no labels.overrides_path set - run package_create first"],
        )
    full_path = resolve_contained(package_dir, overrides_path)
    if full_path is None or not full_path.is_file():
        raise ToolValidationError(
            "override_record",
            [f"package_dir: labels.overrides_path ('{overrides_path}') does not resolve to an existing file inside the package"],
        )

    override_id = kwargs.get("override_id") or f"ovr_{uuid.uuid4().hex[:12]}"
    draft_reason_text = kwargs["draft_reason_text"]
    draft_reason_code = kwargs.get("draft_reason_code") or kwargs["reason_code"]

    row: dict[str, Any] = {
        "override_id": override_id,
        "field_path": kwargs["field_path"],
        "before": kwargs["before"],
        "after": kwargs["after"],
        "reason_code": kwargs["reason_code"],
        "reason_text": kwargs.get("reason_text") or draft_reason_text,
        "author": kwargs.get("author") or f"agent:{override_id}",
        "ts": _now(),
        "agent_draft": {
            "reason_code": draft_reason_code,
            "reason_text": draft_reason_text,
        },
    }
    if kwargs.get("evidence_refs"):
        row["evidence_refs"] = kwargs["evidence_refs"]
    if kwargs.get("bucket") is not None:
        row["bucket"] = kwargs["bucket"]

    # Defensive: the row we just built from validated inputs must itself satisfy the normative
    # override-row shape (labels_row_shape / the P1-P4 schema) before it ever hits disk.
    row_errors = validate_instance(row, load_override_row_schema())
    if row_errors:
        raise ToolValidationError(
            "override_record",
            [f"{error_field_path(e)}: {e.message}" for e in row_errors],
        )

    with full_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")

    return row
