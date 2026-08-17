"""ap_planner_bot.analytics: the P5.2 dashboard's tier-2 pure aggregation over a CorpusScan, and
ap_planner_bot.snapshot_store's append/read of the tier-3 trend file - against the same seeded
drift/clean fixture corpora test_planner_bot_detectors.py uses, so the expected numbers are
grounded in a known corpus, not just "the page renders"."""

from __future__ import annotations

from _planner_bot_corpus import build_clean_corpus, build_drift_corpus

from ap_planner_bot.analytics import build_snapshot, compute_corpus_analytics
from ap_planner_bot.scan import CorpusScan, scan_corpus
from ap_planner_bot.snapshot_store import append_snapshot, read_snapshots


def test_compute_corpus_analytics_empty_scan_is_a_safe_zero_state():
    analytics = compute_corpus_analytics(CorpusScan())
    assert analytics.package_count == 0
    assert analytics.check_stats == ()
    assert analytics.reason_code_stats == ()
    assert analytics.other_reason_code_share == 0.0
    assert analytics.agent_draft_fail_rate is None


def test_compute_corpus_analytics_reason_code_distribution_on_drift_corpus(tmp_path):
    scan = scan_corpus(build_drift_corpus(tmp_path))
    analytics = compute_corpus_analytics(scan)

    assert analytics.package_count == 9
    counts = {s.reason_code: s.count for s in analytics.reason_code_stats}
    assert counts["HOLD_FOR_PRICE_NEGOTIATION"] == 4  # 3 repeated-override + 1 version-drift package
    assert counts["OTHER"] == 3
    assert counts["BOGUS_CODE_NOT_IN_ALLOWLIST"] == 2
    assert analytics.other_reason_code_share == 3 / 9
    for stat in analytics.reason_code_stats:
        assert stat.share == stat.count / 9


def test_compute_corpus_analytics_per_check_fail_and_waiver_rates_on_drift_corpus(tmp_path):
    scan = scan_corpus(build_drift_corpus(tmp_path))
    analytics = compute_corpus_analytics(scan)
    by_id = {s.check_id: s for s in analytics.check_stats}

    engines = by_id["engines_pinned"]
    assert engines.waived_count == 3
    assert engines.fail_count == 0  # a waived fail reads as pass, see ap_gate/checks/registry.py
    assert engines.waiver_rate == 3 / 9

    guideline = by_id["guideline_exists"]
    assert guideline.fail_count == 3
    assert guideline.waived_count == 0
    assert guideline.fail_rate == 3 / 9


def test_compute_corpus_analytics_profile_version_mix_on_drift_corpus(tmp_path):
    scan = scan_corpus(build_drift_corpus(tmp_path))
    analytics = compute_corpus_analytics(scan)
    mix = {(s.profile, s.version): s.count for s in analytics.profile_version_stats}
    assert mix[("commodity_commit_forecast", "0.1")] == 8
    assert mix[("commodity_commit_forecast", "9.9")] == 1


def test_compute_corpus_analytics_agent_draft_fail_rate_present(tmp_path):
    scan = scan_corpus(build_drift_corpus(tmp_path))
    analytics = compute_corpus_analytics(scan)
    # The fixture carries an agent_draft sub-object on every override row (module docstring) so
    # agent_draft_present passes on every package here.
    assert analytics.agent_draft_fail_rate == 0.0


def test_clean_corpus_has_no_other_share_and_no_repeated_signal(tmp_path):
    scan = scan_corpus(build_clean_corpus(tmp_path))
    analytics = compute_corpus_analytics(scan)
    assert analytics.package_count == 3
    assert analytics.other_reason_code_share == 0.0
    by_id = {s.check_id: s for s in analytics.check_stats}
    assert by_id["engines_pinned"].waived_count == 0
    assert by_id["guideline_exists"].fail_count == 0


def test_build_snapshot_is_json_serializable_and_carries_a_timestamp(tmp_path):
    import json

    scan = scan_corpus(build_drift_corpus(tmp_path))
    snapshot = build_snapshot(compute_corpus_analytics(scan), ts="2026-08-16T00:00:00Z")
    json.dumps(snapshot)  # must not raise
    assert snapshot["ts"] == "2026-08-16T00:00:00Z"
    assert snapshot["package_count"] == 9
    assert snapshot["reason_code_counts"]["OTHER"] == 3


def test_snapshot_store_append_and_read_round_trip(tmp_path):
    store_root = tmp_path / "store-root"
    assert read_snapshots(store_root) == []

    append_snapshot(store_root, {"ts": "2026-08-01T00:00:00Z", "package_count": 3})
    append_snapshot(store_root, {"ts": "2026-08-08T00:00:00Z", "package_count": 5})

    rows = read_snapshots(store_root)
    assert [r["package_count"] for r in rows] == [3, 5]  # oldest first, append-only
    assert (store_root / "analytics" / "snapshots.jsonl").is_file()
