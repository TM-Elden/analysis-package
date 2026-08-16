"""P2: per-profile field_path grammar resolution against the reference profile."""

from __future__ import annotations

from ap_gate.field_path import resolve_field_path


def test_resolves_gold_example_field_paths_against_reference_profile():
    cases = [
        ("supplier_forecast.ACME.BBU-100.week_36_qty", "ACME", "BBU-100", "36"),
        ("supplier_forecast.BETA.PSU-50.week_38_qty", "BETA", "PSU-50", "38"),
        ("supplier_forecast.ACME.BBU-SHELF-1.week_37_qty", "ACME", "BBU-SHELF-1", "37"),
    ]
    for field_path, supplier, part, week in cases:
        resolved = resolve_field_path("commodity_commit_forecast", field_path)
        assert resolved is not None, field_path
        assert resolved["output"] == "supplier_forecast"
        assert resolved["value_column"] == "qty"
        assert resolved["keys"] == {"supplier": supplier, "part": part, "week": week}


def test_returns_none_for_unregistered_profile():
    assert resolve_field_path("no_such_profile", "supplier_forecast.ACME.BBU-100.week_36_qty") is None


def test_returns_none_when_field_path_does_not_match_any_template():
    assert resolve_field_path("commodity_commit_forecast", "exception_list.some.other.shape") is None


def test_returns_none_for_wrong_segment_count():
    # 3 segments instead of the declared 4 - must not partially match.
    assert resolve_field_path("commodity_commit_forecast", "supplier_forecast.ACME.week_36_qty") is None
