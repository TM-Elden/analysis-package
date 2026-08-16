"""P4: the agent_draft_present gate check - advisory by default, skip/pass/flag cases,
and the training-grade escalation to required."""

from __future__ import annotations

import json

from conftest import EXAMPLE_PACKAGE

from ap_gate.checks.context import CheckContext
from ap_gate.checks.labels import check_agent_draft_present
from ap_gate.checks.types import SEVERITY_ADVISORY, SEVERITY_REQUIRED
from ap_gate.load_manifest import load_manifest

ROW_WITH_DRAFT = {
    "override_id": "ovr_001",
    "field_path": "supplier_forecast.ACME.BBU-100.week_36_qty",
    "before": 1200,
    "after": 900,
    "reason_code": "HOLD_FOR_PRICE_NEGOTIATION",
    "author": "planner.example",
    "ts": "2025-09-12T21:40:00Z",
    "agent_draft": {"reason_code": "HOLD_FOR_PRICE_NEGOTIATION", "reason_text": "draft rationale"},
}
ROW_WITHOUT_DRAFT = {
    "override_id": "ovr_002",
    "field_path": "supplier_forecast.BETA.PSU-50.week_38_qty",
    "before": 400,
    "after": 400,
    "reason_code": "LTA_LINEARITY_CAP",
    "author": "planner.example",
    "ts": "2025-09-12T21:55:00Z",
}


def _ctx(tmp_path, rows, model_run=None, profile=None):
    manifest = dict(load_manifest(EXAMPLE_PACKAGE))
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "labels").mkdir()
    (pkg / "labels" / "overrides.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    manifest["labels"] = dict(manifest["labels"])
    manifest["labels"]["overrides_path"] = "labels/overrides.jsonl"
    if model_run is not None:
        manifest["model_run"] = model_run
    else:
        manifest.pop("model_run", None)
    if profile is not None:
        manifest["profile"] = profile
    return CheckContext(package_path=pkg, manifest=manifest)


def test_skips_when_model_run_role_absent(tmp_path):
    ctx = _ctx(tmp_path, [ROW_WITHOUT_DRAFT], model_run=None)
    outcome = check_agent_draft_present(ctx)
    assert outcome.result == "skip"


def test_passes_when_all_rows_carry_agent_draft(tmp_path):
    ctx = _ctx(tmp_path, [ROW_WITH_DRAFT], model_run={"assisted": True, "role": "draft_override_suggestions_only"})
    outcome = check_agent_draft_present(ctx)
    assert outcome.result == "pass"


def test_advisory_flag_does_not_block_when_agent_draft_missing(tmp_path):
    ctx = _ctx(
        tmp_path,
        [ROW_WITHOUT_DRAFT],
        model_run={"assisted": True, "role": "draft_override_suggestions_only"},
    )
    outcome = check_agent_draft_present(ctx)
    assert outcome.result == "fail"
    assert outcome.severity == SEVERITY_ADVISORY
    assert not outcome.blocks_overall_pass()
    assert "ovr_002" in outcome.message


def test_gold_example_flags_advisory_not_blocking():
    manifest = load_manifest(EXAMPLE_PACKAGE)
    ctx = CheckContext(package_path=EXAMPLE_PACKAGE, manifest=manifest)
    outcome = check_agent_draft_present(ctx)
    # gold example carries agent_draft on 2/3 rows; the third (ovr_003) is intentionally
    # left without to exercise this exact advisory-flag path.
    assert outcome.result == "fail"
    assert outcome.severity == SEVERITY_ADVISORY
    assert not outcome.blocks_overall_pass()


def test_escalates_to_required_when_profile_opts_in(tmp_path, monkeypatch):
    from ap_gate import profiles as profiles_mod

    monkeypatch.setattr(
        profiles_mod,
        "load_profile_training_grade",
        lambda profile: {"require_agent_draft": True} if profile == "commodity_commit_forecast/0.1" else None,
    )
    monkeypatch.setattr(
        "ap_gate.checks.labels.load_profile_training_grade",
        profiles_mod.load_profile_training_grade,
    )
    ctx = _ctx(
        tmp_path,
        [ROW_WITHOUT_DRAFT],
        model_run={"assisted": True, "role": "draft_override_suggestions_only"},
        profile="commodity_commit_forecast/0.1",
    )
    outcome = check_agent_draft_present(ctx)
    assert outcome.result == "fail"
    assert outcome.severity == SEVERITY_REQUIRED
    assert outcome.blocks_overall_pass()
