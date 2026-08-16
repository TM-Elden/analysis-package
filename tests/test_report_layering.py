"""Report layering is a forward-compatibility + trust requirement (scope item 5), not incidental
shape: results[] must be content-free (no paths/messages) and must never carry person
identifiers (author, owners.*), since it is the layer a future conformance-telemetry
pipeline may consume directly.
"""

import json

from conftest import EXAMPLE_PACKAGE

from ap_gate.checks.context import CheckContext
from ap_gate.checks.registry import run_all
from ap_gate.load_manifest import load_manifest
from ap_gate.report.model import build_report

PERSON_IDENTIFIER_STRINGS = ["planner.example", "lead.example", "pair-agent-1"]


def _report():
    manifest = load_manifest(EXAMPLE_PACKAGE)
    ctx = CheckContext(package_path=EXAMPLE_PACKAGE, manifest=manifest)
    outcomes = run_all(ctx)
    return build_report(
        package_id=manifest["package_id"],
        title=manifest["title"],
        as_of=manifest["as_of"],
        qa_status=manifest["qa"]["status"],
        profile=manifest["profile"],
        outcomes=outcomes,
    )


def test_results_layer_has_only_content_free_keys():
    report = _report()
    for row in report["results"]:
        assert set(row.keys()) == {"check_id", "result", "severity", "waived"}


def test_results_layer_never_contains_paths_or_person_identifiers():
    report = _report()
    results_text = json.dumps(report["results"])
    assert "/" not in results_text.replace("check_id", "").replace("ap_gate", "")  # no path-shaped values
    for identifier in PERSON_IDENTIFIER_STRINGS:
        assert identifier not in results_text


def test_evidence_layer_never_contains_person_identifiers():
    """Evidence messages are for planner-facing path/field fixes, not surveillance of who did what."""
    report = _report()
    evidence_text = json.dumps(report["evidence"])
    for identifier in PERSON_IDENTIFIER_STRINGS:
        assert identifier not in evidence_text


def test_results_and_evidence_are_separate_layers():
    report = _report()
    assert "results" in report and "evidence" in report
    assert report["results"] != report["evidence"]
    result_ids = [r["check_id"] for r in report["results"]]
    evidence_ids = [e["check_id"] for e in report["evidence"]]
    assert result_ids == evidence_ids
