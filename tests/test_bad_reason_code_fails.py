from conftest import FIXTURES

from ap_gate.checks.context import CheckContext
from ap_gate.checks.registry import run_all
from ap_gate.load_manifest import load_manifest

PACKAGE = FIXTURES / "broken_reason_code"


def test_bad_reason_code_fails():
    manifest = load_manifest(PACKAGE)
    ctx = CheckContext(package_path=PACKAGE, manifest=manifest)
    outcomes = {o.check_id: o for o in run_all(ctx)}

    assert outcomes["reason_codes_known"].result == "fail"
    assert "MADE_UP_CODE" in outcomes["reason_codes_known"].message
