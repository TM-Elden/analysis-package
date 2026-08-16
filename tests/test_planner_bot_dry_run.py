"""C7 dry-run (`ap_planner_bot.dry_run`): a seeded corpus + a scratch profile-file change that
flips a known check's outcome for a known package, asserted via the diff `dry_run` returns."""

from __future__ import annotations

from _planner_bot_corpus import build_clean_corpus

from ap_planner_bot.dry_run import dry_run

PROFILE = "commodity_commit_forecast"


def test_dry_run_no_op_change_reports_no_movement(tmp_path):
    store = build_clean_corpus(tmp_path)
    store_root = tmp_path / "store-root-noop"

    result = dry_run(store, store_root, PROFILE, {})

    assert result.newly_failing_packages == ()
    assert result.newly_passing_packages == ()
    assert result.check_movements == ()
    assert result.evaluated_version == "0.1"


def test_dry_run_flips_a_known_package_to_newly_failing(tmp_path):
    store = build_clean_corpus(tmp_path)
    store_root = tmp_path / "store-root-narrow"

    # clean_a's override row uses HOLD_FOR_PRICE_NEGOTIATION (see _planner_bot_corpus.py) -
    # drop it from the allow-list and that package's reason_codes_known check must flip to fail.
    proposed = {
        "reason_codes.json": {
            "reason_codes": ["LTA_LINEARITY_CAP", "SUPPLIER_RISK_SPLIT_CHANGE"],
            "other_requires_reason_text": True,
        }
    }
    result = dry_run(store, store_root, PROFILE, proposed)

    assert result.evaluated_version == "0.1"

    # Exactly one package moves - clean_b/clean_c use reason codes still in the narrowed
    # allow-list, unaffected.
    assert len(result.newly_failing_packages) == 1
    assert result.newly_passing_packages == ()

    reason_movements = [m for m in result.check_movements if m.check_id == "reason_codes_known"]
    assert len(reason_movements) == 1
    assert reason_movements[0].before == "pass"
    assert reason_movements[0].after == "fail"

    # the newly-failing package and the moved check both name the same package.
    moved_key = f"{reason_movements[0].package_id}@{reason_movements[0].package_version}"
    assert moved_key in result.newly_failing_packages


def test_dry_run_widening_allowlist_can_flip_a_failure_to_pass(tmp_path):
    store = build_clean_corpus(tmp_path)

    # Establish a genuine failing baseline: seed store_root's *real* registry with a narrowed
    # 0.1 allow-list (the same version every clean-corpus package declares), so
    # reason_codes_known already fails for clean_a before any dry_run call. Then dry-run a
    # widened proposal against that baseline and confirm it flips back to pass.
    from ap_registry.profile_registry import ProfileRegistry

    store_root = tmp_path / "store-root-seeded"
    real_registry = ProfileRegistry(store_root)
    real_registry.seed_version(
        PROFILE,
        "0.1",
        {"reason_codes.json": {"reason_codes": ["LTA_LINEARITY_CAP", "SUPPLIER_RISK_SPLIT_CHANGE"]}},
    )

    widened = {
        "reason_codes.json": {
            "reason_codes": ["HOLD_FOR_PRICE_NEGOTIATION", "LTA_LINEARITY_CAP", "SUPPLIER_RISK_SPLIT_CHANGE"],
            "other_requires_reason_text": True,
        }
    }
    result = dry_run(store, store_root, PROFILE, widened)

    assert result.newly_failing_packages == ()
    assert len(result.newly_passing_packages) == 1
    reason_movements = [m for m in result.check_movements if m.check_id == "reason_codes_known"]
    assert len(reason_movements) == 1
    assert reason_movements[0].before == "fail"
    assert reason_movements[0].after == "pass"
