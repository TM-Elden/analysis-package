"""fathm-ap MCP tools: schema coverage, override_record's P4 capture contract, and the
package_create -> package_check -> package_finalize round trip."""

from __future__ import annotations

import json

import pytest

from ap_gate.schema import load_override_row_schema, validate_instance
from ap_mcp.errors import ToolValidationError
from ap_mcp.tools import TOOL_SCHEMAS, override_record, package_check, package_create, package_finalize


def test_tool_schemas_cover_the_capture_kit_minimum():
    assert {"package_create", "package_check", "package_finalize", "override_record"} <= TOOL_SCHEMAS.keys()
    for name, schema in TOOL_SCHEMAS.items():
        assert schema["description"]
        assert schema["input_schema"]["type"] == "object"


def test_override_record_requires_draft_reason_text():
    assert "draft_reason_text" in TOOL_SCHEMAS["override_record"]["input_schema"]["required"]


def test_override_record_missing_draft_reason_text_is_rejected(tmp_path):
    pkg_dir = package_create(dest_dir=str(tmp_path / "pkg"), title="Test pack", analyst_id="tom.analyst")
    overrides_path = pkg_dir / "labels" / "overrides.jsonl"
    before_lines = overrides_path.read_text(encoding="utf-8").splitlines()

    with pytest.raises(ToolValidationError) as excinfo:
        override_record(
            package_dir=str(pkg_dir),
            field_path="supplier_forecast.ACME.BBU-100.week_36_qty",
            before=1200,
            after=900,
            reason_code="HOLD_FOR_PRICE_NEGOTIATION",
            # draft_reason_text deliberately omitted
        )

    message = str(excinfo.value)
    assert "draft_reason_text" in message
    assert "now" in message.lower()  # planner-serving: capture it now, while still in context

    # capture never happened - a rejected call appends no row
    after_lines = overrides_path.read_text(encoding="utf-8").splitlines()
    assert after_lines == before_lines


def test_override_record_complete_call_writes_a_schema_valid_row_with_agent_draft(tmp_path):
    pkg_dir = package_create(dest_dir=str(tmp_path / "pkg"), title="Test pack", analyst_id="tom.analyst")

    row = override_record(
        package_dir=str(pkg_dir),
        field_path="supplier_forecast.ACME.BBU-100.week_36_qty",
        before=1200,
        after=900,
        reason_code="HOLD_FOR_PRICE_NEGOTIATION",
        draft_reason_text="Draft: hold ~300u off ACME pending price talks - confirm exact cut with planner",
    )

    # verifiable against the P1-P4 shipped schema
    assert not validate_instance(row, load_override_row_schema())

    assert row["agent_draft"]["reason_code"] == "HOLD_FOR_PRICE_NEGOTIATION"
    assert row["agent_draft"]["reason_text"] == (
        "Draft: hold ~300u off ACME pending price talks - confirm exact cut with planner"
    )
    # top-level fields are seeded from the same call, so the row is immediately schema-valid and
    # capture never depends on a human accepting it later
    assert row["reason_code"] == "HOLD_FOR_PRICE_NEGOTIATION"
    assert row["author"]
    assert row["ts"]

    overrides_path = pkg_dir / "labels" / "overrides.jsonl"
    lines = [line for line in overrides_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    written = json.loads(lines[-1])
    assert written == row


def test_override_record_preserves_draft_when_human_later_edits_top_level_fields(tmp_path):
    pkg_dir = package_create(dest_dir=str(tmp_path / "pkg"), title="Test pack", analyst_id="tom.analyst")

    row = override_record(
        package_dir=str(pkg_dir),
        field_path="supplier_forecast.BETA.PSU-50.week_38_qty",
        before=400,
        after=400,
        reason_code="LTA_LINEARITY_CAP",
        draft_reason_text="Draft: flag only, cap likely binds weeks 38-40",
    )

    overrides_path = pkg_dir / "labels" / "overrides.jsonl"
    lines = overrides_path.read_text(encoding="utf-8").splitlines()
    idx = len(lines) - 1
    edited = dict(row)
    edited["reason_code"] = "PLANNER_CONFIRMED_CAP"
    edited["reason_text"] = "Confirmed: cap binds, no qty change"
    edited["author"] = "planner.example"
    lines[idx] = json.dumps(edited)
    overrides_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    final = json.loads(overrides_path.read_text(encoding="utf-8").splitlines()[idx])
    assert final["reason_code"] == "PLANNER_CONFIRMED_CAP"
    assert final["author"] == "planner.example"
    # agent_draft is untouched - capture didn't depend on the human's acceptance
    assert final["agent_draft"] == row["agent_draft"]


def test_package_create_check_finalize_round_trip(tmp_path):
    pkg_dir = package_create(dest_dir=str(tmp_path / "pkg"), title="Tool test pack", analyst_id="tom.analyst")

    report = package_check(package_dir=str(pkg_dir))
    assert report["overall"] == "pass"

    result = package_finalize(
        package_dir=str(pkg_dir),
        store_root=str(tmp_path / "store"),
        actor_id="tom.analyst",
        actor_roles="analyst",
    )
    assert result["status"] == "draft"
    assert result["gate_overall"] == "pass"


def test_package_finalize_rejects_missing_required_param(tmp_path):
    pkg_dir = package_create(dest_dir=str(tmp_path / "pkg"), title="Test pack", analyst_id="tom.analyst")
    with pytest.raises(ToolValidationError) as excinfo:
        package_finalize(package_dir=str(pkg_dir), store_root=str(tmp_path / "store"), actor_id="tom.analyst")
    assert "actor_roles" in str(excinfo.value)
