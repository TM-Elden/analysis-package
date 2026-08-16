"""labels_paths, labels_jsonl_parse, reason_codes_known."""

from __future__ import annotations

import json

from ap_gate.checks.context import CheckContext
from ap_gate.checks.types import CheckOutcome
from ap_gate.profiles import load_profile_reason_codes, profile_short_name

CHECK_ID_LABELS_PATHS = "labels_paths"
CHECK_ID_LABELS_JSONL_PARSE = "labels_jsonl_parse"
CHECK_ID_REASON_CODES_KNOWN = "reason_codes_known"

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
        if not (pkg / rel_path).is_file():
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
        full_path = pkg / rel_path
        if not full_path.is_file():
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
    allowlist = load_profile_reason_codes(profile_name) if profile_name else None
    if allowlist is None:
        return CheckOutcome.skip(
            CHECK_ID_REASON_CODES_KNOWN,
            f"no reason-code allow-list registered for profile {profile!r} "
            "(no profiles/<name>/reason_codes.json) - skipping",
        )

    overrides_path = (ctx.manifest.get("labels") or {}).get("overrides_path")
    if not overrides_path:
        return CheckOutcome.skip(CHECK_ID_REASON_CODES_KNOWN, "labels.overrides_path not set - cannot check reason codes")
    full_path = ctx.package_path / overrides_path
    if not full_path.is_file():
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
