"""Gate-analytics tier 2: pure aggregation over a `CorpusScan`, feeding the manager-persona
dashboard (design report `data/fathm-phase5-readiness/report.md` section 5.2 in the firstmate
repo). One computation engine, not two: this module consumes the exact same `CorpusScan` object
`ap_planner_bot.detectors.run_all_detectors` already consumes - it does not re-scan or re-derive
anything `scan.py` computed. No I/O here; `ap_planner_bot.snapshot_store` owns the
`analytics/snapshots.jsonl` file, `ap_console.routes` and `ap_planner_bot.sweep` are the only
callers of this module.

**Hard invariant (see CLAUDE.md's dashboard section): nothing here reads or emits `author`,
`analyst_id`, `reviewer_id`, or any `owners.*` identifier.** `PackageScan` (scan.py) already
structurally cannot carry one - `OverrideRow` drops `author` at parse time and `PackageScan` itself
only carries `package_id`/`package_version`/`profile`/`outcomes`/`override_rows`, none of them
`PackageRecord`'s `analyst_id`/`reviewer_id` columns. This module never takes a `PackageRecord` or a
`PackageStore` as input - only a `CorpusScan` - so there is nothing here for a person identifier to
ride in on. `tests/test_planner_bot_detectors.py::test_no_author_or_owner_keys_anywhere_in_scan_or_findings`
is extended (not duplicated) to cover this module's output too - see that file.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass
from typing import Any

from ap_gate.checks.types import RESULT_FAIL
from ap_gate.profiles import profile_short_name
from ap_planner_bot.scan import CorpusScan

#: The one advisory-severity check today (see CLAUDE.md's ap-gate architecture section) - its fail
#: rate is surfaced as its own dashboard tile per the task brief, in addition to appearing in
#: check_stats like every other check.
ADVISORY_DRAFT_CHECK_ID = "agent_draft_present"


@dataclass(frozen=True)
class CheckStat:
    """One check's rates across the scanned corpus. `fail_count`/`waived_count` are both counted
    against `total` (the number of packages this check ran an outcome for) - a check that `skip`s
    on some packages (e.g. `no_unlabeled_diff`, permanently stubbed) still contributes to `total`,
    its skip just isn't a fail or a waiver."""

    check_id: str
    severity: str
    total: int
    fail_count: int  # result == fail (post-waiver - a waived fail already reads as pass, see registry.py)
    waived_count: int
    fail_rate: float
    waiver_rate: float


@dataclass(frozen=True)
class ReasonCodeStat:
    reason_code: str
    count: int
    share: float  # of all override rows in the corpus, not just this profile's


@dataclass(frozen=True)
class ProfileVersionStat:
    profile: str
    version: str
    count: int


@dataclass(frozen=True)
class CorpusAnalytics:
    package_count: int
    check_stats: tuple[CheckStat, ...] = ()
    reason_code_stats: tuple[ReasonCodeStat, ...] = ()
    other_reason_code_share: float = 0.0
    profile_version_stats: tuple[ProfileVersionStat, ...] = ()
    #: None when the advisory check never produced an outcome in this corpus (empty scan).
    agent_draft_fail_rate: float | None = None


def compute_corpus_analytics(scan: CorpusScan) -> CorpusAnalytics:
    """The tier-2 computation: per-check fail/waiver rates, reason-code distribution + OTHER
    share, and profile-version mix, all aggregated by check_id / reason_code / profile only."""
    package_count = len(scan.packages)
    if package_count == 0:
        return CorpusAnalytics(package_count=0)

    totals: Counter[str] = Counter()
    fails: Counter[str] = Counter()
    waived: Counter[str] = Counter()
    severities: dict[str, str] = {}
    for pkg in scan.packages:
        for check_id, outcome in pkg.outcomes.items():
            totals[check_id] += 1
            severities[check_id] = outcome.severity
            if outcome.waived:
                waived[check_id] += 1
            elif outcome.result == RESULT_FAIL:
                fails[check_id] += 1

    check_stats = tuple(
        CheckStat(
            check_id=check_id,
            severity=severities[check_id],
            total=total,
            fail_count=fails[check_id],
            waived_count=waived[check_id],
            fail_rate=fails[check_id] / total,
            waiver_rate=waived[check_id] / total,
        )
        for check_id, total in sorted(totals.items())
    )

    reason_counts: Counter[str] = Counter()
    other_count = 0
    for pkg in scan.packages:
        for row in pkg.override_rows:
            reason_counts[row.reason_code] += 1
            if row.reason_code == "OTHER":
                other_count += 1
    total_rows = sum(reason_counts.values())
    reason_code_stats = tuple(
        ReasonCodeStat(reason_code=code, count=count, share=count / total_rows if total_rows else 0.0)
        for code, count in sorted(reason_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    other_share = other_count / total_rows if total_rows else 0.0

    version_counts: Counter[tuple[str, str]] = Counter()
    for pkg in scan.packages:
        name = profile_short_name(pkg.profile) or ""
        _, _, version = pkg.profile.partition("/")
        version_counts[(name, version or "")] += 1
    profile_version_stats = tuple(
        ProfileVersionStat(profile=name, version=version, count=count)
        for (name, version), count in sorted(version_counts.items())
    )

    advisory_stat = next((s for s in check_stats if s.check_id == ADVISORY_DRAFT_CHECK_ID), None)
    agent_draft_fail_rate = advisory_stat.fail_rate if advisory_stat is not None else None

    return CorpusAnalytics(
        package_count=package_count,
        check_stats=check_stats,
        reason_code_stats=reason_code_stats,
        other_reason_code_share=other_share,
        profile_version_stats=profile_version_stats,
        agent_draft_fail_rate=agent_draft_fail_rate,
    )


def build_snapshot(analytics: CorpusAnalytics, *, ts: str | None = None) -> dict[str, Any]:
    """The one aggregate row appended to `analytics/snapshots.jsonl` per run (task brief: "ts,
    corpus size, per-check fail/waiver rates, reason-code counts, profile mix - NO person
    identifiers"). A plain JSON-serializable dict, not a dataclass - it is a wire/file format, and
    keeping it a dict here (rather than a `to_dict()` on `CorpusAnalytics`) makes the forbidden-keys
    shape trivially greppable at the one place it is produced.

    `ts` is injectable for deterministic tests; defaults to real UTC now.
    """
    return {
        "ts": ts or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "package_count": analytics.package_count,
        "check_stats": [
            {
                "check_id": s.check_id,
                "severity": s.severity,
                "total": s.total,
                "fail_count": s.fail_count,
                "waived_count": s.waived_count,
                "fail_rate": s.fail_rate,
                "waiver_rate": s.waiver_rate,
            }
            for s in analytics.check_stats
        ],
        "reason_code_counts": {s.reason_code: s.count for s in analytics.reason_code_stats},
        "other_reason_code_share": analytics.other_reason_code_share,
        "profile_version_counts": {
            f"{s.profile}/{s.version}" if s.version else s.profile: s.count
            for s in analytics.profile_version_stats
        },
        "agent_draft_fail_rate": analytics.agent_draft_fail_rate,
    }
