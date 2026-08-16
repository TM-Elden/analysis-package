"""Regression coverage for the review-fix commit (waiver-order bug + path containment).

Two behaviors added after the initial feat commit, neither previously covered:

1. Waivers must be applied to `outcomes` *before* `qa_approved_implies_pass` runs,
   not only after. Otherwise a waived required-check failure still shows up as
   blocking to the meta check, so `qa.status: approved` + a valid waiver would
   still fail the gate - defeating the point of a waiver.
2. Every check that resolves a manifest-declared path must reject a path that
   escapes the package directory (`..` traversal or an absolute path) instead
   of silently following it (`Path.__truediv__` treats an absolute RHS as an
   override).
"""

from conftest import FIXTURES

from ap_gate.checks.context import CheckContext
from ap_gate.checks.registry import run_all
from ap_gate.load_manifest import load_manifest

PACKAGE = FIXTURES / "broken_engine_path"


def test_waived_failing_check_does_not_block_qa_approved_implies_pass():
    manifest = load_manifest(PACKAGE)
    assert manifest["qa"]["status"] == "approved"  # fixture precondition

    manifest["qa"]["waivers"] = [
        {"check_id": "engines_pinned", "reason": "known gap, tracked for phase 2", "author": "reviewer.example"}
    ]
    ctx = CheckContext(package_path=PACKAGE, manifest=manifest)
    outcomes = {o.check_id: o for o in run_all(ctx)}

    engines = outcomes["engines_pinned"]
    assert engines.result == "pass"
    assert engines.waived is True

    meta = outcomes["qa_approved_implies_pass"]
    assert meta.result == "pass", meta.message


def test_unwaived_failing_check_still_blocks_qa_approved_implies_pass():
    """Control: without the waiver, the same fixture's dangling engine path still blocks."""
    manifest = load_manifest(PACKAGE)
    ctx = CheckContext(package_path=PACKAGE, manifest=manifest)
    outcomes = {o.check_id: o for o in run_all(ctx)}

    assert outcomes["engines_pinned"].result == "fail"
    assert outcomes["qa_approved_implies_pass"].result == "fail"


def test_engine_path_escaping_package_dir_fails_contained_not_followed():
    manifest = load_manifest(PACKAGE)
    manifest["engines"][0]["path"] = "../../../../../../etc/passwd"
    ctx = CheckContext(package_path=PACKAGE, manifest=manifest)
    outcomes = {o.check_id: o for o in run_all(ctx)}

    engines = outcomes["engines_pinned"]
    assert engines.result == "fail"
    assert "resolves outside the package directory" in engines.message


def test_guideline_path_escaping_package_dir_fails_contained_not_followed():
    manifest = load_manifest(PACKAGE)
    manifest["method"]["guideline_path"] = "/etc/passwd"
    ctx = CheckContext(package_path=PACKAGE, manifest=manifest)
    outcomes = {o.check_id: o for o in run_all(ctx)}

    guideline = outcomes["guideline_exists"]
    assert guideline.result == "fail"
    assert "resolves outside the package directory" in guideline.message
