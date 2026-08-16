from conftest import FIXTURES

from ap_gate.checks.context import CheckContext
from ap_gate.checks.registry import run_all
from ap_gate.load_manifest import load_manifest

PACKAGE = FIXTURES / "broken_manifest_fields"


def test_unsupported_standard_version_fails():
    manifest = load_manifest(PACKAGE)
    ctx = CheckContext(package_path=PACKAGE, manifest=manifest)
    outcomes = {o.check_id: o for o in run_all(ctx)}

    assert outcomes["standard_version"].result == "fail"
    assert "ap/0.9" in outcomes["standard_version"].message
    # must_fields cannot resolve a schema for an unsupported version - skip, not a
    # confusing second failure with no clear fix.
    assert outcomes["must_fields"].result == "skip"
