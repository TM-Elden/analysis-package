"""fathm-ap MCP tool implementations: package_create, package_check, package_finalize,
override_record, package_submit_review, package_status.

Thin layer, per the design report (`data/fathm-contract-enforcement-research/report.md` §6 in the
firstmate repo): every tool here calls the exact same library functions the rest of the codebase
uses - `ap_agent_tools.tools` for create/check/publish, `ap_gate.load_manifest` /
`ap_gate.checks.pathsafe` / `ap_gate.schema` for the override row, `ap_review.ReviewWorkflow` /
`ap_store.PackageStore` for submit/status. Nothing here re-implements gate, manifest, or review
logic.

`override_record` is the P4-critical tool (design report §6 item 2): `draft_reason_text` is a
required schema parameter, so a call cannot structurally omit the agent's draft rationale - the
call *is* the capture. The written row carries `agent_draft: {reason_code, reason_text}` (the
draft, exactly as submitted) plus top-level `reason_code`/`reason_text`/`author` seeded from the
same call, so the row is immediately schema-valid and capture never depends on a human accepting it
later; a subsequent human edit (existing C10 review flow, out of scope here) can change the
top-level fields while `agent_draft` stays untouched as the historical record.

`package_submit_review` is the NC.1 tool (`data/fathm-native-chat-readiness/report.md` §5.1/§5.2 in
the firstmate repo): it closes the one missing step in the planner authoring loop
(create -> check -> [override_record]* -> finalize -> submit_review). It wraps
`ap_review.ReviewWorkflow.transition(draft -> in_review)` against the local store, mirroring
`package_finalize`'s actor/store_root argument shape exactly (`package_id`/`package_version`
instead of `package_dir`, since it operates on an already-published store record, not a working
directory) - `ReviewWorkflow` owns policy (role check, gate-before-review), so a policy rejection
(e.g. gate-before-review failure) surfaces as a `ToolValidationError` with the workflow's own
planner-serving message, never a stack trace. `package_status` is the optional cheap sibling: a
read-only `PackageStore.get` so an agent can answer "did my pack get approved?" without leaving the
conversation.

**NC.2 remote mode** (`data/fathm-native-chat-readiness/report.md` §5.2 in the firstmate repo):
`package_finalize`/`package_submit_review` check `ap_mcp.remote.remote_mode_config()` (env-selected
via `AP_API_URL`/`AP_API_TOKEN`, both required) first - if set, they call the real HTTP API
(`POST /packages/upload`, `POST /packages/{id}/review`) via `ap_mcp.remote.RemoteApiClient` instead
of touching a local store, and `store_root`/`actor_id`/`actor_roles` are ignored (identity comes
from the bearer token server-side). `package_create`/`package_check`/`override_record` never
consult remote mode at all - they always operate on the planner's own working tree, local or
remote harness alike, per the design report's explicit "these stay local" call.
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
from ap_mcp.remote import RemoteApiClient, RemoteApiError, remote_mode_config
from ap_review.policy import ReviewPolicy
from ap_review.workflow import ReviewPolicyError, ReviewWorkflow
from ap_store.store import PackageStore, StoreError

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "package_create": _AGENT_TOOL_SCHEMAS["package.create"],
    "package_check": _AGENT_TOOL_SCHEMAS["package.check"],
    "package_finalize": {
        "description": (
            "Finalize a package: publish it to the package store as an immutable "
            "package_version. Does not require the gate to pass first - gate status is recorded on "
            "the store record; call package_check first if you need to know it will pass review. "
            "Local mode (default): writes directly to the store at store_root, identified by "
            "actor_id/actor_roles (ap_store.PackageStore, the same function `ap-agent-tools` and "
            "`ap-api` use) - store_root/actor_id/actor_roles are then required. Remote mode "
            "(AP_API_URL and AP_API_TOKEN both set in the server's environment): uploads the "
            "package over HTTP to POST /packages/upload on that API instead, authenticated by the "
            "bearer token - store_root/actor_id/actor_roles are ignored and not needed, since "
            "identity comes from the token."
        ),
        "input_schema": {
            "type": "object",
            "required": ["package_dir"],
            "properties": {
                "package_dir": {"type": "string"},
                "store_root": {"type": "string", "description": "PackageStore root directory - local mode only, required unless AP_API_URL/AP_API_TOKEN are set"},
                "actor_id": {"type": "string", "description": "local mode only, required unless AP_API_URL/AP_API_TOKEN are set"},
                "actor_roles": {"type": "string", "description": "comma-separated role names, e.g. 'analyst' - local mode only, required unless AP_API_URL/AP_API_TOKEN are set"},
            },
        },
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
    "package_submit_review": {
        "description": (
            "Submit a published package_version for review: draft -> in_review "
            "(ap_review.ReviewWorkflow.transition), so it appears in the manager's console review "
            "queue. Requires the analyst role; by default also requires ap-gate check to pass "
            "against the package's stored bytes (ReviewPolicy.gate_before_review) - a policy "
            "rejection (wrong role, failing gate) comes back as a planner-serving message here, "
            "not a stack trace. Call package_finalize first to publish the package_version. "
            "Local mode (default): store_root/actor_id/actor_roles are required, same shape as "
            "package_finalize. Remote mode (AP_API_URL and AP_API_TOKEN both set in the server's "
            "environment): calls POST /packages/{id}/review on that API instead, authenticated by "
            "the bearer token - store_root/actor_id/actor_roles are ignored and not needed."
        ),
        "input_schema": {
            "type": "object",
            "required": ["package_id", "package_version"],
            "properties": {
                "package_id": {"type": "string"},
                "package_version": {"type": "string"},
                "store_root": {"type": "string", "description": "PackageStore root directory - local mode only, required unless AP_API_URL/AP_API_TOKEN are set"},
                "actor_id": {"type": "string", "description": "local mode only, required unless AP_API_URL/AP_API_TOKEN are set"},
                "actor_roles": {"type": "string", "description": "comma-separated role names, e.g. 'analyst' - local mode only, required unless AP_API_URL/AP_API_TOKEN are set"},
            },
        },
    },
    "package_status": {
        "description": (
            "Read one package's live status from the store (draft, in_review, approved, "
            "rejected) - e.g. to answer 'did my pack get approved?' without leaving the "
            "conversation. Omit package_version to get the most recently published version."
        ),
        "input_schema": {
            "type": "object",
            "required": ["package_id", "store_root"],
            "properties": {
                "package_id": {"type": "string"},
                "package_version": {"type": "string", "description": "Omit for the most recently published version"},
                "store_root": {"type": "string", "description": "PackageStore root directory"},
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


def _build_remote_client(api_url: str, api_token: str) -> RemoteApiClient:
    """The one seam between package_finalize/package_submit_review and ap_mcp.remote.RemoteApiClient
    - tests monkeypatch this to inject a TestClient-backed transport instead of real network (see
    tests/test_mcp_remote_mode.py), the same "swap the construction seam" pattern
    ap_api/deps.py's cached dependency getters use for get_llm_client etc."""
    return RemoteApiClient(api_url, api_token)


def _require_local_mode_fields(tool_name: str, kwargs: dict[str, Any], fields: tuple[str, ...]) -> None:
    """local mode's store_root/actor_id/actor_roles are schema-optional (remote mode doesn't need
    them) but still required once we know we're in local mode - enforced here instead of the
    schema, with the same planner-serving phrasing validate_arguments uses for a missing required
    field."""
    missing = [f for f in fields if not kwargs.get(f)]
    if missing:
        raise ToolValidationError(
            tool_name,
            [
                f"{f}: required in local mode (AP_API_URL/AP_API_TOKEN are not both set) - this tool call must include it"
                for f in missing
            ],
        )


def package_finalize(**kwargs: Any) -> dict[str, Any]:
    validate_arguments("package_finalize", kwargs, TOOL_SCHEMAS["package_finalize"]["input_schema"])

    remote = remote_mode_config()
    if remote is not None:
        api_url, api_token = remote
        client = _build_remote_client(api_url, api_token)
        try:
            body = client.publish(kwargs["package_dir"])
        except RemoteApiError as exc:
            raise ToolValidationError("package_finalize", [str(exc)]) from exc
        finally:
            client.close()
        return {
            "package_id": body["package_id"],
            "package_version": body["package_version"],
            "status": body["status"],
            "gate_overall": body["gate_overall"],
        }

    _require_local_mode_fields("package_finalize", kwargs, ("store_root", "actor_id", "actor_roles"))
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


def package_submit_review(**kwargs: Any) -> dict[str, Any]:
    """Submit a published package_version for review (draft -> in_review). Policy failures
    (wrong role, gate-before-review) raise ToolValidationError with the workflow's own
    planner-serving message; a store-level conflict (StoreError) is likewise never a bare
    traceback. See package_finalize's docstring for the local/remote-mode split - identical
    reasoning applies here."""
    validate_arguments("package_submit_review", kwargs, TOOL_SCHEMAS["package_submit_review"]["input_schema"])

    remote = remote_mode_config()
    if remote is not None:
        api_url, api_token = remote
        client = _build_remote_client(api_url, api_token)
        try:
            body = client.submit_review(kwargs["package_id"], kwargs["package_version"])
        except RemoteApiError as exc:
            raise ToolValidationError("package_submit_review", [str(exc)]) from exc
        finally:
            client.close()
        return {
            "package_id": body["package_id"],
            "package_version": body["package_version"],
            "status": body["status"],
        }

    _require_local_mode_fields("package_submit_review", kwargs, ("store_root", "actor_id", "actor_roles"))
    actor = Identity(id=kwargs["actor_id"], roles=parse_roles(kwargs["actor_roles"]))
    with PackageStore(kwargs["store_root"]) as store:
        workflow = ReviewWorkflow(store=store, policy=ReviewPolicy())
        try:
            record = workflow.transition(
                kwargs["package_id"],
                kwargs["package_version"],
                to_status="in_review",
                actor=actor,
            )
        except (ReviewPolicyError, StoreError) as exc:
            raise ToolValidationError("package_submit_review", [str(exc)]) from exc
    return {
        "package_id": record.package_id,
        "package_version": record.package_version,
        "status": record.status,
    }


def package_status(**kwargs: Any) -> dict[str, Any]:
    """Read one package_version's live store status (or the most recently published version, if
    package_version is omitted)."""
    validate_arguments("package_status", kwargs, TOOL_SCHEMAS["package_status"]["input_schema"])
    with PackageStore(kwargs["store_root"]) as store:
        record = store.get(kwargs["package_id"], kwargs.get("package_version"))
    if record is None:
        raise ToolValidationError(
            "package_status",
            [
                f"package_id: no such package{'/' + kwargs['package_version'] if kwargs.get('package_version') else ''} "
                f"in store at {kwargs['store_root']!r} - check package_finalize actually published it"
            ],
        )
    return {
        "package_id": record.package_id,
        "package_version": record.package_version,
        "status": record.status,
        "profile": record.profile,
        "title": record.title,
        "gate_overall": record.gate_overall,
        "analyst_id": record.analyst_id,
        "reviewer_id": record.reviewer_id,
    }
