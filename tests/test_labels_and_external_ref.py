"""Positive edge cases from the MVP doc test plan: empty label files parse fine,
and an external_ref-only input (no path) passes inputs_pinned.
"""

from conftest import EXAMPLE_PACKAGE

from ap_gate.checks.context import CheckContext
from ap_gate.checks.labels import check_labels_jsonl_parse
from ap_gate.checks.inputs import check_inputs_pinned
from ap_gate.load_manifest import load_manifest


def test_empty_label_lines_parse_ok(tmp_path):
    manifest = load_manifest(EXAMPLE_PACKAGE)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "labels").mkdir()
    for name in ("overrides.jsonl", "judgments.jsonl", "truths_applied.jsonl"):
        (pkg / "labels" / name).write_text("", encoding="utf-8")
    manifest = dict(manifest)
    manifest["labels"] = {
        "overrides_path": "labels/overrides.jsonl",
        "judgments_path": "labels/judgments.jsonl",
        "truths_applied_path": "labels/truths_applied.jsonl",
    }
    ctx = CheckContext(package_path=pkg, manifest=manifest)
    outcome = check_labels_jsonl_parse(ctx)
    assert outcome.result == "pass"


def test_external_ref_input_passes_without_path():
    manifest = load_manifest(EXAMPLE_PACKAGE)
    ctx = CheckContext(package_path=EXAMPLE_PACKAGE, manifest=manifest)
    outcome = check_inputs_pinned(ctx)
    # example includes exactly one external_ref input (lta_linearity_note) alongside 5 pinned files
    assert outcome.result == "pass"
