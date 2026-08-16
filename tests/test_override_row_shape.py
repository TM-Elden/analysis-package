"""P1: override-row.schema.json validation and the labels_row_shape gate check.

Uses the gold example as a base manifest (its labels/ files already exist) and swaps in
tmp_path override rows to isolate each case, matching the pattern in
test_labels_and_external_ref.py.
"""

from __future__ import annotations

import json

from conftest import EXAMPLE_PACKAGE

from ap_gate.checks.context import CheckContext
from ap_gate.checks.labels import check_labels_row_shape
from ap_gate.load_manifest import load_manifest
from ap_gate.schema import load_override_row_schema, validate_instance

VALID_ROW = {
    "override_id": "ovr_001",
    "field_path": "supplier_forecast.ACME.BBU-100.week_36_qty",
    "before": 1200,
    "after": 900,
    "reason_code": "HOLD_FOR_PRICE_NEGOTIATION",
    "author": "planner.example",
    "ts": "2025-09-12T21:40:00Z",
}


def _pkg_with_overrides(tmp_path, rows: list[dict], profile: str | None = None):
    manifest = dict(load_manifest(EXAMPLE_PACKAGE))
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "labels").mkdir()
    (pkg / "labels" / "overrides.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""), encoding="utf-8"
    )
    manifest["labels"] = dict(manifest["labels"])
    manifest["labels"]["overrides_path"] = "labels/overrides.jsonl"
    if profile is not None:
        manifest["profile"] = profile
    return CheckContext(package_path=pkg, manifest=manifest)


# --- schema-level validation ---


def test_valid_row_has_no_schema_errors():
    schema = load_override_row_schema()
    assert validate_instance(VALID_ROW, schema) == []


def test_row_missing_required_field_fails_schema():
    schema = load_override_row_schema()
    row = dict(VALID_ROW)
    del row["author"]
    errors = validate_instance(row, schema)
    assert any("author" in str(e.message) or "author" in list(e.path) for e in errors) or errors


def test_reason_text_and_evidence_refs_are_optional_in_core():
    schema = load_override_row_schema()
    # VALID_ROW has neither reason_text nor evidence_refs and still validates.
    assert "reason_text" not in VALID_ROW
    assert "evidence_refs" not in VALID_ROW
    assert validate_instance(VALID_ROW, schema) == []


def test_agent_draft_sub_object_validates_when_present():
    schema = load_override_row_schema()
    row = dict(VALID_ROW, agent_draft={"reason_code": "HOLD_FOR_PRICE_NEGOTIATION"})
    assert validate_instance(row, schema) == []


def test_agent_draft_missing_reason_code_fails_schema():
    schema = load_override_row_schema()
    row = dict(VALID_ROW, agent_draft={"reason_text": "draft, no code"})
    errors = validate_instance(row, schema)
    assert errors


# --- gate check: pass/fail/skip ---


def test_labels_row_shape_passes_on_gold_example():
    manifest = load_manifest(EXAMPLE_PACKAGE)
    ctx = CheckContext(package_path=EXAMPLE_PACKAGE, manifest=manifest)
    outcome = check_labels_row_shape(ctx)
    assert outcome.result == "pass"


def test_labels_row_shape_fails_on_missing_required_field(tmp_path):
    bad_row = dict(VALID_ROW)
    del bad_row["ts"]
    ctx = _pkg_with_overrides(tmp_path, [VALID_ROW, bad_row])
    outcome = check_labels_row_shape(ctx)
    assert outcome.result == "fail"
    assert outcome.severity == "required"
    assert "labels/overrides.jsonl" in outcome.paths


def test_labels_row_shape_skips_when_overrides_path_missing(tmp_path):
    manifest = dict(load_manifest(EXAMPLE_PACKAGE))
    manifest["labels"] = dict(manifest["labels"])
    manifest["labels"]["overrides_path"] = "labels/does_not_exist.jsonl"
    ctx = CheckContext(package_path=EXAMPLE_PACKAGE, manifest=manifest)
    outcome = check_labels_row_shape(ctx)
    assert outcome.result == "skip"


def test_labels_row_shape_ignores_malformed_json_lines(tmp_path):
    """labels_jsonl_parse owns malformed-JSON reporting; row_shape must not double-report or crash."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "labels").mkdir()
    (pkg / "labels" / "overrides.jsonl").write_text(
        json.dumps(VALID_ROW) + "\nnot json at all\n", encoding="utf-8"
    )
    manifest = dict(load_manifest(EXAMPLE_PACKAGE))
    manifest["labels"] = dict(manifest["labels"])
    manifest["labels"]["overrides_path"] = "labels/overrides.jsonl"
    ctx = CheckContext(package_path=pkg, manifest=manifest)
    outcome = check_labels_row_shape(ctx)
    assert outcome.result == "pass"  # the one valid row passes; the garbage line is skipped here


# --- training-grade profile escalation (reason_text) ---


def test_reason_text_permissive_by_default_for_registered_profile(tmp_path):
    # commodity_commit_forecast/0.1 ships training_grade.json with require_reason_text: false.
    row_without_reason_text = dict(VALID_ROW)
    ctx = _pkg_with_overrides(tmp_path, [row_without_reason_text], profile="commodity_commit_forecast/0.1")
    outcome = check_labels_row_shape(ctx)
    assert outcome.result == "pass"


def test_reason_text_required_when_profile_opts_in(tmp_path, monkeypatch):
    from ap_gate import profiles as profiles_mod

    monkeypatch.setattr(
        profiles_mod,
        "load_profile_training_grade",
        lambda profile: {"require_reason_text": True} if profile == "commodity_commit_forecast/0.1" else None,
    )
    monkeypatch.setattr(
        "ap_gate.checks.labels.load_profile_training_grade",
        profiles_mod.load_profile_training_grade,
    )
    row_without_reason_text = dict(VALID_ROW)
    ctx = _pkg_with_overrides(tmp_path, [row_without_reason_text], profile="commodity_commit_forecast/0.1")
    outcome = check_labels_row_shape(ctx)
    assert outcome.result == "fail"
    assert "reason_text" in outcome.message
