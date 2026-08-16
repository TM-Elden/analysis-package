from conftest import FIXTURES

from ap_gate.checks.context import CheckContext
from ap_gate.checks.registry import run_all
from ap_gate.load_manifest import load_manifest

PACKAGE = FIXTURES / "broken_missing_output"


def test_missing_output_fails_output_contract_files():
    manifest = load_manifest(PACKAGE)
    ctx = CheckContext(package_path=PACKAGE, manifest=manifest)
    outcomes = {o.check_id: o for o in run_all(ctx)}

    assert outcomes["output_contract_files"].result == "fail"
    assert "exceptions.csv" in outcomes["output_contract_files"].message
    # approved status is now inconsistent with the real check results
    assert outcomes["qa_approved_implies_pass"].result == "fail"


def test_missing_output_fails_cli_exit_code():
    from ap_gate.cli import main

    assert main(["check", str(PACKAGE)]) == 1
