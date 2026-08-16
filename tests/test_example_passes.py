"""Gold-pack regression: the committed example must always pass ap-gate.

This is the phase-1 CI regression the task requires - if this test starts
failing, the example package (or the gate) broke, and CI fails on it.
"""

from conftest import EXAMPLE_PACKAGE

from ap_gate.checks.context import CheckContext
from ap_gate.checks.registry import ALL_CHECK_IDS, run_all
from ap_gate.load_manifest import load_manifest


def test_example_passes_gate():
    manifest = load_manifest(EXAMPLE_PACKAGE)
    ctx = CheckContext(package_path=EXAMPLE_PACKAGE, manifest=manifest)
    outcomes = run_all(ctx)

    failing = [o for o in outcomes if o.blocks_overall_pass()]
    assert not failing, "\n".join(f"{o.check_id}: {o.message}" for o in failing)

    seen_ids = {o.check_id for o in outcomes}
    assert seen_ids == set(ALL_CHECK_IDS)


def test_example_passes_via_cli(capsys):
    from ap_gate.cli import main

    exit_code = main(["check", str(EXAMPLE_PACKAGE)])
    assert exit_code == 0


def test_no_unlabeled_diff_is_skipped_not_faked():
    """The example must not claim no_unlabeled_diff passed - it's stubbed in phase 1."""
    manifest = load_manifest(EXAMPLE_PACKAGE)
    ctx = CheckContext(package_path=EXAMPLE_PACKAGE, manifest=manifest)
    outcomes = {o.check_id: o for o in run_all(ctx)}
    assert outcomes["no_unlabeled_diff"].result == "skip"
