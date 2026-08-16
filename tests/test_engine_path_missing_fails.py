"""engines_pinned must fail when engines[].path is set but the file doesn't exist (scope item 4)."""

from conftest import FIXTURES

from ap_gate.checks.context import CheckContext
from ap_gate.checks.registry import run_all
from ap_gate.load_manifest import load_manifest

PACKAGE = FIXTURES / "broken_engine_path"


def test_dangling_engine_path_fails():
    manifest = load_manifest(PACKAGE)
    ctx = CheckContext(package_path=PACKAGE, manifest=manifest)
    outcomes = {o.check_id: o for o in run_all(ctx)}

    assert outcomes["engines_pinned"].result == "fail"
    assert "bom_explode.py" in outcomes["engines_pinned"].message
