"""P3: evidence_refs fragment syntax parsing."""

from __future__ import annotations

from ap_gate.evidence_refs import parse_evidence_ref


def test_whole_file_ref_has_no_fragment():
    ref = parse_evidence_ref("inputs/supplier_splits.csv")
    assert ref.path == "inputs/supplier_splits.csv"
    assert ref.row_filters == {}
    assert not ref.has_fragment


def test_external_ref_uri_has_no_fragment():
    ref = parse_evidence_ref("contracts://supplier-ACME/LTA-2024-section-4.2")
    assert ref.path == "contracts://supplier-ACME/LTA-2024-section-4.2"
    assert ref.row_filters == {}


def test_single_row_filter_fragment_parses():
    ref = parse_evidence_ref("inputs/supplier_splits.csv#rows=part:BBU-100")
    assert ref.path == "inputs/supplier_splits.csv"
    assert ref.row_filters == {"part": "BBU-100"}
    assert ref.has_fragment


def test_multi_column_row_filter_fragment_parses():
    ref = parse_evidence_ref("inputs/rack_demand.csv#rows=part:BBU-100,week:2025-W36")
    assert ref.path == "inputs/rack_demand.csv"
    assert ref.row_filters == {"part": "BBU-100", "week": "2025-W36"}


def test_malformed_fragment_degrades_to_no_filter_not_an_exception():
    ref = parse_evidence_ref("inputs/supplier_splits.csv#not-a-rows-fragment")
    assert ref.path == "inputs/supplier_splits.csv"
    assert ref.row_filters == {}
