"""labels_paths, labels_jsonl_parse, labels_row_shape, reason_codes_known, agent_draft_present."""

from __future__ import annotations

import json
from pathlib import Path

from ap_gate.checks.context import CheckContext
from ap_gate.checks.pathsafe import resolve_contained
from ap_gate.checks.types import CheckOutcome
from ap_gate.profiles import (
    UnknownProfileVersionError,
    load_profile_reason_codes,
    load_profile_training_grade,
    profile_short_name,
)
from ap_gate.schema import error_field_path, load_override_row_schema, validate_instance

CHECK_ID_LABELS_PATHS = "labels_paths"
CHECK_ID_LABELS_JSONL_PARSE = "labels_jsonl_parse"
CHECK_ID_LABELS_ROW_SHAPE = "labels_row_shape"
CHECK_ID_REASON_CODES_KNOWN = "reason_codes_known"
CHECK_ID_AGENT_DRAFT_PRESENT = "agent_draft_present"

LABEL_KEYS = ("overrides_path", "judgments_path", "truths_applied_path")


def _label_paths(ctx: CheckContext) -> dict[str, str | None]:
    labels = ctx.manifest.get("labels") or {}
    return {key: labels.get(key) for key in LABEL_KEYS}


def check_labels_paths(ctx: CheckContext) -> CheckOutcome:
    pkg = ctx.package_path
    problems: list[str] = []
    paths: list[str] = []

    for key, rel_path in _label_paths(ctx).items():
        if not rel_path:
            problems.append(f"labels.{key} is not set in MANIFEST.yaml")
            continue
        full_path = resolve_contained(pkg, rel_path)
        if full_path is None:
            problems.append(f"labels.{key} points to '{rel_path}' which resolves outside the package directory")
            paths.append(rel_path)
        elif not full_path.is_file():
            problems.append(f"labels.{key} points to '{rel_path}' which does not exist")
            paths.append(rel_path)

    if problems:
        return CheckOutcome.fail(
            CHECK_ID_LABELS_PATHS,
            "Label file problems (files may be empty, but must exist):\n"
            + "\n".join(f"  - {p}" for p in problems)
            + "\n  Create the missing file(s) (an empty file is valid) and fix any MANIFEST.yaml path.",
            paths=paths,
        )
    return CheckOutcome.ok(CHECK_ID_LABELS_PATHS, "all three label files exist")


def check_labels_jsonl_parse(ctx: CheckContext) -> CheckOutcome:
    pkg = ctx.package_path
    problems: list[str] = []
    paths: list[str] = []
    checked = 0

    for key, rel_path in _label_paths(ctx).items():
        if not rel_path:
            continue
        full_path = resolve_contained(pkg, rel_path)
        if full_path is None or not full_path.is_file():
            continue  # labels_paths already reports this
        checked += 1
        for lineno, line in enumerate(full_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                problems.append(f"labels.{key} ('{rel_path}') line {lineno}: not valid JSON ({exc.msg})")
                if rel_path not in paths:
                    paths.append(rel_path)
                continue
            if not isinstance(obj, dict):
                problems.append(f"labels.{key} ('{rel_path}') line {lineno}: JSON value is not an object")
                if rel_path not in paths:
                    paths.append(rel_path)

    if problems:
        return CheckOutcome.fail(
            CHECK_ID_LABELS_JSONL_PARSE,
            "Label JSONL parse problems:\n" + "\n".join(f"  - {p}" for p in problems)
            + "\n  Fix the malformed line(s) so each non-empty line is one JSON object.",
            paths=paths,
        )
    return CheckOutcome.ok(CHECK_ID_LABELS_JSONL_PARSE, f"{checked} label file(s) parse cleanly")


def check_reason_codes_known(ctx: CheckContext) -> CheckOutcome:
    profile = ctx.manifest.get("profile")
    profile_name = profile_short_name(profile)
    try:
        # Pass the raw manifest value (not the stripped short name) so a registry-configured
        # gate resolves the package's declared version - see ap_gate.profiles module docstring.
        allowlist = load_profile_reason_codes(profile) if profile_name else None
    except UnknownProfileVersionError as exc:
        return CheckOutcome.fail(CHECK_ID_REASON_CODES_KNOWN, str(exc))
    if allowlist is None:
        return CheckOutcome.skip(
            CHECK_ID_REASON_CODES_KNOWN,
            f"no reason-code allow-list registered for profile {profile!r} "
            "(no profiles/<name>/reason_codes.json) - skipping",
        )

    overrides_path = (ctx.manifest.get("labels") or {}).get("overrides_path")
    if not overrides_path:
        return CheckOutcome.skip(CHECK_ID_REASON_CODES_KNOWN, "labels.overrides_path not set - cannot check reason codes")
    full_path = resolve_contained(ctx.package_path, overrides_path)
    if full_path is None or not full_path.is_file():
        return CheckOutcome.skip(
            CHECK_ID_REASON_CODES_KNOWN, f"labels.overrides_path '{overrides_path}' does not exist - cannot check reason codes"
        )

    codes = set(allowlist.get("reason_codes", []))
    other_requires_text = bool(allowlist.get("other_requires_reason_text"))
    problems: list[str] = []

    for lineno, line in enumerate(full_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue  # labels_jsonl_parse already reports this
        if not isinstance(obj, dict):
            continue
        override_id = obj.get("override_id") or f"line {lineno}"
        code = obj.get("reason_code")
        if code not in codes:
            problems.append(
                f"{overrides_path} ({override_id}): reason_code {code!r} is not in the "
                f"'{profile_name}' allow-list {sorted(codes)}"
            )
            continue
        if code == "OTHER" and other_requires_text and not obj.get("reason_text"):
            problems.append(f"{overrides_path} ({override_id}): reason_code OTHER requires a non-empty reason_text")

    if problems:
        return CheckOutcome.fail(
            CHECK_ID_REASON_CODES_KNOWN,
            "Reason code problems:\n" + "\n".join(f"  - {p}" for p in problems),
            paths=[overrides_path],
        )
    return CheckOutcome.ok(CHECK_ID_REASON_CODES_KNOWN, f"all override reason codes valid for profile '{profile_name}'")


def _resolve_overrides_file(ctx: CheckContext) -> tuple[str | None, Path | None]:
    """Shared by labels_row_shape and agent_draft_present: resolve labels.overrides_path,
    or (path-or-None, None) if unset/missing - labels_paths already reports that case."""
    overrides_path = (ctx.manifest.get("labels") or {}).get("overrides_path")
    if not overrides_path:
        return None, None
    full_path = resolve_contained(ctx.package_path, overrides_path)
    if full_path is None or not full_path.is_file():
        return overrides_path, None
    return overrides_path, full_path


def _iter_override_rows(full_path: Path):
    """Yield (lineno, row) for each non-empty line that parses as a JSON object.
    Malformed lines are skipped - labels_jsonl_parse already reports those."""
    for lineno, line in enumerate(full_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield lineno, obj


def check_labels_row_shape(ctx: CheckContext) -> CheckOutcome:
    """P1: validate every labels/overrides.jsonl row against the normative
    override-row.schema.json. reason_text is required only when the package's profile
    has opted into training_grade.json's require_reason_text (core stays permissive)."""
    overrides_path, full_path = _resolve_overrides_file(ctx)
    if overrides_path is None:
        return CheckOutcome.skip(CHECK_ID_LABELS_ROW_SHAPE, "labels.overrides_path not set - cannot check row shape")
    if full_path is None:
        return CheckOutcome.skip(
            CHECK_ID_LABELS_ROW_SHAPE, f"labels.overrides_path '{overrides_path}' does not exist - cannot check row shape"
        )

    profile = ctx.manifest.get("profile")
    profile_name = profile_short_name(profile)
    try:
        training_grade = load_profile_training_grade(profile) if profile_name else None
    except UnknownProfileVersionError as exc:
        return CheckOutcome.fail(CHECK_ID_LABELS_ROW_SHAPE, str(exc))
    require_reason_text = bool(training_grade and training_grade.get("require_reason_text"))

    schema = load_override_row_schema()
    problems: list[str] = []
    checked = 0

    for lineno, row in _iter_override_rows(full_path):
        checked += 1
        row_id = row.get("override_id") or f"line {lineno}"
        for error in validate_instance(row, schema):
            problems.append(f"{overrides_path} ({row_id}){error_field_path(error)}: {error.message}")
        if require_reason_text and not row.get("reason_text"):
            problems.append(
                f"{overrides_path} ({row_id}): reason_text is required by profile "
                f"'{profile_name}' (training_grade.require_reason_text)"
            )

    if problems:
        return CheckOutcome.fail(
            CHECK_ID_LABELS_ROW_SHAPE,
            "Override row shape problems:\n" + "\n".join(f"  - {p}" for p in problems)
            + "\n  Fix each row in labels/overrides.jsonl to match the normative override-row schema "
            "(standard/ap-0.2/schemas/override-row.schema.json).",
            paths=[overrides_path],
        )
    return CheckOutcome.ok(CHECK_ID_LABELS_ROW_SHAPE, f"{checked} override row(s) match the normative schema")


def check_agent_draft_present(ctx: CheckContext) -> CheckOutcome:
    """P4: flag (advisory by default) override rows missing agent_draft when the package
    declares agent participation (model_run.role, C8). Never fails core - a training-grade
    profile may escalate via training_grade.json's require_agent_draft."""
    model_role = (ctx.manifest.get("model_run") or {}).get("role")
    if not model_role:
        return CheckOutcome.skip(
            CHECK_ID_AGENT_DRAFT_PRESENT, "model_run.role not set - package does not declare agent participation"
        )

    overrides_path, full_path = _resolve_overrides_file(ctx)
    if overrides_path is None:
        return CheckOutcome.skip(CHECK_ID_AGENT_DRAFT_PRESENT, "labels.overrides_path not set - cannot check agent_draft")
    if full_path is None:
        return CheckOutcome.skip(
            CHECK_ID_AGENT_DRAFT_PRESENT, f"labels.overrides_path '{overrides_path}' does not exist - cannot check agent_draft"
        )

    profile = ctx.manifest.get("profile")
    profile_name = profile_short_name(profile)
    try:
        training_grade = load_profile_training_grade(profile) if profile_name else None
    except UnknownProfileVersionError as exc:
        # training_grade.json never got a chance to load, so require_agent_draft's opt-in
        # is unknown - stay advisory by default (this check's "never fails core" invariant)
        # rather than escalating to a hard block on an unrelated fail-closed knob.
        return CheckOutcome.advisory_fail(CHECK_ID_AGENT_DRAFT_PRESENT, str(exc))
    require_agent_draft = bool(training_grade and training_grade.get("require_agent_draft"))

    missing: list[str] = []
    checked = 0
    for lineno, row in _iter_override_rows(full_path):
        checked += 1
        if not row.get("agent_draft"):
            missing.append(row.get("override_id") or f"line {lineno}")

    if not missing:
        return CheckOutcome.ok(CHECK_ID_AGENT_DRAFT_PRESENT, f"all {checked} override row(s) carry agent_draft")

    message = (
        f"{len(missing)}/{checked} override row(s) missing agent_draft while model_run.role={model_role!r} "
        f"declares agent participation: {', '.join(missing)}\n"
        "  Capture the agent's draft reason_code/reason_text on the row before the human override "
        "lands, so it isn't discarded - see the agent_draft sub-object in override-row.schema.json."
    )
    if require_agent_draft:
        return CheckOutcome.fail(CHECK_ID_AGENT_DRAFT_PRESENT, message, paths=[overrides_path])
    return CheckOutcome.advisory_fail(CHECK_ID_AGENT_DRAFT_PRESENT, message, paths=[overrides_path])
