"""ap_planner_bot.detectors: the five v0 deterministic drift detectors, against the seeded
injected-drift / clean fixture corpora (`_planner_bot_corpus.py`)."""

from __future__ import annotations

import dataclasses

from _planner_bot_corpus import (
    OTHER_THEME_TEXT,
    REPEATED_FIELD_PATH,
    REPEATED_REASON_CODE,
    UNKNOWN_REASON_CODE,
    build_clean_corpus,
    build_drift_corpus,
)

from ap_planner_bot.analytics import build_snapshot, compute_corpus_analytics
from ap_planner_bot.detectors import (
    ALL_DETECTORS,
    Finding,
    detect_gate_failure_hotspots,
    detect_profile_version_drift,
    detect_reason_code_issues,
    detect_repeated_overrides,
    detect_repeated_waivers,
    run_all_detectors,
)
from ap_planner_bot.scan import scan_corpus

# Identifiers that must never appear as a Finding.detail key or value - see detectors.py's
# module docstring and test_no_author_or_owner_keys_anywhere_in_scan_or_findings below.
_FORBIDDEN_KEYS = {"author", "owners", "owner", "analyst_id", "reviewer_id", "created_by_id", "decided_by_id"}
_FORBIDDEN_VALUES = {"planner.drift-fixture", "lead.drift-fixture", "planner.clean-fixture", "lead.clean-fixture"}


def test_detect_reason_code_issues_flags_unknown_code_and_other_theme(tmp_path):
    scan = scan_corpus(build_drift_corpus(tmp_path))
    findings = detect_reason_code_issues(scan)

    unknown = [f for f in findings if f.detector == "reason_code_unknown"]
    assert unknown and unknown[0].detail["reason_code"] == UNKNOWN_REASON_CODE
    assert unknown[0].detail["count"] >= 2
    assert all(f.kind == "reason_code_add" for f in unknown)

    other_heavy = [f for f in findings if f.detector == "reason_code_other_heavy"]
    assert other_heavy and other_heavy[0].detail["reason_text"] == OTHER_THEME_TEXT
    assert other_heavy[0].detail["count"] >= 3


def test_detect_repeated_waivers_flags_the_waived_check(tmp_path):
    scan = scan_corpus(build_drift_corpus(tmp_path))
    findings = detect_repeated_waivers(scan)

    engines = [f for f in findings if f.detail.get("check_id") == "engines_pinned"]
    assert engines, findings
    assert engines[0].kind == "profile_change"
    assert engines[0].detail["count"] >= 3
    assert len(set(engines[0].package_ids)) == engines[0].detail["count"]


def test_detect_repeated_overrides_aggregates_by_field_path_and_reason_code(tmp_path):
    scan = scan_corpus(build_drift_corpus(tmp_path))
    findings = detect_repeated_overrides(scan)

    match = [
        f
        for f in findings
        if f.detail.get("field_path") == REPEATED_FIELD_PATH and f.detail.get("reason_code") == REPEATED_REASON_CODE
    ]
    assert match, findings
    assert match[0].detail["count"] >= 3


def test_detect_gate_failure_hotspots_flags_the_broken_check(tmp_path):
    scan = scan_corpus(build_drift_corpus(tmp_path))
    findings = detect_gate_failure_hotspots(scan)

    guideline = [f for f in findings if f.detail.get("check_id") == "guideline_exists"]
    assert guideline, findings
    assert guideline[0].detail["fail_rate"] >= 0.3


def test_detect_profile_version_drift_flags_the_unknown_version(tmp_path):
    scan = scan_corpus(build_drift_corpus(tmp_path))
    findings = detect_profile_version_drift(scan)

    assert findings, findings
    assert any("9.9" in f.detail["declared_versions"] for f in findings)
    assert all(f.kind == "profile_change" for f in findings)


def test_run_all_detectors_end_to_end_on_drift_corpus_finds_every_kind(tmp_path):
    scan = scan_corpus(build_drift_corpus(tmp_path))
    findings = run_all_detectors(scan)
    detectors_seen = {f.detector for f in findings}

    assert detectors_seen == {
        "reason_code_unknown",
        "reason_code_other_heavy",
        "repeated_waivers",
        "repeated_overrides",
        "gate_failure_hotspot",
        "profile_version_drift",
    }


def test_run_all_detectors_end_to_end_on_clean_corpus_finds_nothing(tmp_path):
    scan = scan_corpus(build_clean_corpus(tmp_path))
    findings = run_all_detectors(scan)
    assert findings == []


def test_no_dead_end_questions_detector_exists():
    """Deferred per the design report (no question log, planner-incentive-stance territory) -
    must not silently reappear as one of the five."""
    names = {fn.__name__ for fn in ALL_DETECTORS}
    assert len(ALL_DETECTORS) == 5
    assert not any("dead_end" in n or "question" in n for n in names)


def test_no_author_or_owner_keys_anywhere_in_scan_or_findings(tmp_path):
    """Non-negotiable (design report section 7, extended to the P5.2 dashboard by
    `data/fathm-phase5-readiness/report.md` section 5.2): a detector - or dashboard - output must
    never key off - or leak - an author/owner identifier, however indirectly. Checks the scan's
    own aggregable data (OverrideRow has no author field at all - see scan.py), every Finding's
    detail dict, and (P5.2 addition) the dashboard's own analytics/snapshot payload
    (`ap_planner_bot.analytics`) - the store-stats tier is the one place a `PackageRecord`'s
    `analyst_id`/`reviewer_id` columns are reachable at all (see ap_console/routes.py's
    `_dashboard_tier1_context`, which deliberately never touches them; this test instead asserts
    the fact at the analytics/scan layer, which is the layer this test file already owns)."""
    for corpus_builder in (build_drift_corpus, build_clean_corpus):
        store = corpus_builder(tmp_path / corpus_builder.__name__)
        scan = scan_corpus(store)

        for pkg in scan.packages:
            for row in pkg.override_rows:
                assert set(dataclasses.asdict(row)) <= {"field_path", "reason_code", "reason_text"}

        for finding in run_all_detectors(scan):
            for key, value in finding.detail.items():
                assert key not in _FORBIDDEN_KEYS, f"{finding.detector} detail has forbidden key {key!r}"
                if isinstance(value, str):
                    assert value not in _FORBIDDEN_VALUES, f"{finding.detector} detail leaked an identity: {value!r}"
            assert not _FORBIDDEN_VALUES & set(finding.package_ids)

        analytics = compute_corpus_analytics(scan)
        snapshot = build_snapshot(analytics)
        _assert_no_forbidden_identifiers(snapshot)


def _assert_no_forbidden_identifiers(obj, *, path: str = "$") -> None:
    """Recursively walks a JSON-shaped value (dict/list/scalar) - the dashboard's snapshot dict -
    asserting no key is a forbidden identifier name and no string value is one of the fixture's
    known author/reviewer ids. Recursive so it also covers nested structures a future snapshot
    field might add, not just the top level."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key not in _FORBIDDEN_KEYS, f"{path}.{key} is a forbidden key"
            _assert_no_forbidden_identifiers(value, path=f"{path}.{key}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _assert_no_forbidden_identifiers(item, path=f"{path}[{i}]")
    elif isinstance(obj, str):
        assert obj not in _FORBIDDEN_VALUES, f"{path} leaked an identity: {obj!r}"


def test_finding_is_a_plain_typed_dataclass():
    f = Finding(detector="x", kind="reason_code_add", summary="s", package_ids=("pkg_1",))
    assert dataclasses.is_dataclass(f)
    assert f.detail == {}
