"""C6's stage-1 detectors: turn a `CorpusScan` into typed `Finding`s. Pure functions over
`scan.py`'s output - no I/O, no LLM call. Stage 2 (turning a `Finding` into a drafted proposal)
is a later chunk (design report `data/fathm-phase4-readiness/report.md` section 5.3, P4.4) and
is out of scope here on purpose: the LLM never computes a stat itself, it only narrates findings
this module already computed deterministically.

**Hard invariant: no detector aggregates by `author` or any `owners.*` identifier - ever.**
This is not a style preference, it is the load-bearing mitigation the phase-4 plan adopts for the
still-open `fathm-plan-review-decision-planner-incentive-stance` hold (report section 7): a bot
whose input is "repeated overrides" is one `GROUP BY author` away from a planner league table.
`scan.py`'s `OverrideRow` structurally cannot carry `author` (it's dropped at parse time), so the
enforcement point is really there - but
`test_planner_bot_detectors.py::test_no_author_or_owner_keys_anywhere_in_scan_or_findings`
still asserts no `Finding.detail` key or value contains an author/owner identifier, so a future
detector can't reintroduce one by reading the manifest's `owners` block directly.

Thresholds (the "N" in "waived >= N packages" etc.) are named constants below, each documented at
its definition as tunable - same honesty pattern as the entropy threshold in
`ap_redact/secrets_scan.py`: expected to move once tuned against the real pilot corpus, not load-
bearing math.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ap_gate.checks.types import RESULT_FAIL
from ap_gate.profiles import load_profile_reason_codes, profile_short_name
from ap_planner_bot.scan import CorpusScan

#: A distinct OTHER reason_text repeated at least this many times (across packages) reads as a
#: recurring theme worth a real reason code, not noise.
OTHER_THEME_MIN_COUNT = 3

#: An out-of-allowlist reason_code used at least this many times is worth flagging (a single
#: one-off typo isn't).
UNKNOWN_REASON_CODE_MIN_COUNT = 2

#: A check waived across at least this many distinct packages suggests the check itself (or the
#: profile requirement behind it) needs tuning, not that N planners independently hit the same bug.
REPEATED_WAIVER_MIN_PACKAGES = 3

#: The same (field_path, reason_code) pair overridden across at least this many distinct packages
#: suggests the Standard/profile should account for it directly.
REPEATED_OVERRIDE_MIN_PACKAGES = 3

#: A required check must fail (unwaived) on at least this many packages, at at least this fail
#: rate, to count as a "hotspot" rather than one package's honest one-off problem.
GATE_HOTSPOT_MIN_PACKAGES = 3
GATE_HOTSPOT_MIN_FAIL_RATE = 0.3


@dataclass(frozen=True)
class Finding:
    """One deterministic drift signal, ready for the (later, P4.4) LLM drafting stage to narrate
    into a proposal. `detail` is structured evidence for that stage - keys are always one of
    `field_path` / `reason_code` / `check_id` / `profile` / `count` / `fail_rate` /
    `reason_text` / `declared_versions` / `known_versions`, **never** an author/owner identifier.
    """

    detector: str  # which function produced this, e.g. "reason_code_other_heavy"
    kind: str  # candidate proposal kind: reason_code_add | profile_change | check_add | standard_change
    summary: str  # human-facing, package/field/check-level only - no person identifiers
    package_ids: tuple[str, ...]  # evidence: which approved packages support this finding
    detail: dict[str, Any] = field(default_factory=dict)


def _profile_known_reason_codes(profile_name: str) -> set[str] | None:
    allowlist = load_profile_reason_codes(profile_name)
    if allowlist is None:
        return None
    return set(allowlist.get("reason_codes", []))


def detect_reason_code_issues(scan: CorpusScan) -> list[Finding]:
    """Unknown-code and OTHER-heavy-with-a-recurring-theme reason codes -> candidate reason_code_add.

    Aggregated by (profile, reason_code[, reason_text]) only.
    """
    unknown_hits: dict[tuple[str, str], list[str]] = defaultdict(list)
    other_theme_hits: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    known_by_profile: dict[str, set[str] | None] = {}

    for pkg in scan.packages:
        profile_name = profile_short_name(pkg.profile) or ""
        if profile_name not in known_by_profile:
            known_by_profile[profile_name] = _profile_known_reason_codes(profile_name)
        known = known_by_profile[profile_name]

        for row in pkg.override_rows:
            if known is not None and row.reason_code not in known:
                unknown_hits[(profile_name, row.reason_code)].append(pkg.package_id)
            elif row.reason_code == "OTHER" and row.reason_text:
                other_theme_hits[(profile_name, row.reason_code, row.reason_text)].append(pkg.package_id)

    findings: list[Finding] = []
    for (profile_name, code), package_ids in unknown_hits.items():
        if len(package_ids) < UNKNOWN_REASON_CODE_MIN_COUNT:
            continue
        findings.append(
            Finding(
                detector="reason_code_unknown",
                kind="reason_code_add",
                summary=f"reason_code {code!r} used {len(package_ids)} time(s) but is not in "
                f"profile {profile_name!r}'s allow-list",
                package_ids=tuple(sorted(set(package_ids))),
                detail={"profile": profile_name, "reason_code": code, "count": len(package_ids)},
            )
        )
    for (profile_name, code, reason_text), package_ids in other_theme_hits.items():
        if len(package_ids) < OTHER_THEME_MIN_COUNT:
            continue
        findings.append(
            Finding(
                detector="reason_code_other_heavy",
                kind="reason_code_add",
                summary=f"OTHER used {len(package_ids)} time(s) in profile {profile_name!r} with the "
                f"same recurring reason_text - candidate for a dedicated reason_code",
                package_ids=tuple(sorted(set(package_ids))),
                detail={
                    "profile": profile_name,
                    "reason_code": code,
                    "reason_text": reason_text,
                    "count": len(package_ids),
                },
            )
        )
    return findings


def detect_repeated_waivers(scan: CorpusScan) -> list[Finding]:
    """Same check waived across >= N distinct packages -> candidate profile_change/check_add."""
    waived_packages: dict[str, list[str]] = defaultdict(list)
    for pkg in scan.packages:
        for check_id, outcome in pkg.outcomes.items():
            if outcome.waived:
                waived_packages[check_id].append(pkg.package_id)

    findings: list[Finding] = []
    for check_id, package_ids in waived_packages.items():
        distinct = sorted(set(package_ids))
        if len(distinct) < REPEATED_WAIVER_MIN_PACKAGES:
            continue
        findings.append(
            Finding(
                detector="repeated_waivers",
                kind="profile_change",
                summary=f"check {check_id!r} waived on {len(distinct)} distinct package(s) - "
                "candidate to tune the requirement or add a dedicated check",
                package_ids=tuple(distinct),
                detail={"check_id": check_id, "count": len(distinct)},
            )
        )
    return findings


def detect_repeated_overrides(scan: CorpusScan) -> list[Finding]:
    """Same (field_path, reason_code) overridden across >= N distinct packages ->
    candidate profile_change/standard_change.

    **Aggregated by field_path and reason_code only - never by author.** This is the detector the
    no-author-aggregation invariant is most directly about (module docstring); do not add an
    author/owner dimension to the grouping key below.
    """
    pattern_packages: dict[tuple[str, str], list[str]] = defaultdict(list)
    for pkg in scan.packages:
        for row in pkg.override_rows:
            pattern_packages[(row.field_path, row.reason_code)].append(pkg.package_id)

    findings: list[Finding] = []
    for (field_path, reason_code), package_ids in pattern_packages.items():
        distinct = sorted(set(package_ids))
        if len(distinct) < REPEATED_OVERRIDE_MIN_PACKAGES:
            continue
        findings.append(
            Finding(
                detector="repeated_overrides",
                kind="profile_change",
                summary=f"field_path {field_path!r} overridden with reason_code {reason_code!r} "
                f"on {len(distinct)} distinct package(s)",
                package_ids=tuple(distinct),
                detail={"field_path": field_path, "reason_code": reason_code, "count": len(distinct)},
            )
        )
    return findings


def detect_gate_failure_hotspots(scan: CorpusScan) -> list[Finding]:
    """Per-check unwaived-fail rate across the fresh rescan -> candidate check/profile_change."""
    total = len(scan.packages)
    if total == 0:
        return []

    fail_packages: dict[str, list[str]] = defaultdict(list)
    for pkg in scan.packages:
        for check_id, outcome in pkg.outcomes.items():
            if outcome.result == RESULT_FAIL and not outcome.waived:
                fail_packages[check_id].append(pkg.package_id)

    findings: list[Finding] = []
    for check_id, package_ids in fail_packages.items():
        distinct = sorted(set(package_ids))
        fail_rate = len(distinct) / total
        if len(distinct) < GATE_HOTSPOT_MIN_PACKAGES or fail_rate < GATE_HOTSPOT_MIN_FAIL_RATE:
            continue
        findings.append(
            Finding(
                detector="gate_failure_hotspot",
                kind="profile_change",
                summary=f"check {check_id!r} fails on {len(distinct)}/{total} package(s) "
                f"({fail_rate:.0%}) in the current rescan",
                package_ids=tuple(distinct),
                detail={"check_id": check_id, "count": len(distinct), "total": total, "fail_rate": fail_rate},
            )
        )
    return findings


def _known_profile_versions() -> dict[str, set[str]]:
    """Registry placeholder (design report section 5.5's versioned profile registry is a later
    chunk, P4.3): today the only source of a profile's "known" version is its own
    `profiles/<name>/reason_codes.json` `profile_version` field, resolved via the same
    `ap_gate.profiles` loader every check uses. Keeps the shape ready for P4.3 to swap in a real
    registry query without touching this detector's call site.
    """
    from ap_gate.profiles import PROFILES_ROOT

    known: dict[str, set[str]] = {}
    if not PROFILES_ROOT.is_dir():
        return known
    for profile_dir in PROFILES_ROOT.iterdir():
        allowlist = load_profile_reason_codes(profile_dir.name)
        version = allowlist.get("profile_version") if allowlist else None
        if version:
            known[profile_dir.name] = {str(version)}
    return known


def detect_profile_version_drift(scan: CorpusScan) -> list[Finding]:
    """Packages declaring a `<profile>/<version>` the registry doesn't recognize -> flag only
    (no registry to compare against yet - see `_known_profile_versions`'s docstring)."""
    known = _known_profile_versions()
    drift_packages: dict[tuple[str, str], list[str]] = defaultdict(list)

    for pkg in scan.packages:
        if "/" not in pkg.profile:
            continue
        name, _, version = pkg.profile.partition("/")
        known_versions = known.get(name)
        if known_versions is not None and version not in known_versions:
            drift_packages[(name, version)].append(pkg.package_id)

    findings: list[Finding] = []
    for (name, version), package_ids in drift_packages.items():
        distinct = sorted(set(package_ids))
        findings.append(
            Finding(
                detector="profile_version_drift",
                kind="profile_change",
                summary=f"{len(distinct)} package(s) declare profile {name!r} version {version!r}, "
                f"not in the known version set {sorted(known.get(name, set()))}",
                package_ids=tuple(distinct),
                detail={
                    "profile": name,
                    "declared_versions": [version],
                    "known_versions": sorted(known.get(name, set())),
                    "count": len(distinct),
                },
            )
        )
    return findings


#: Deliberately excludes a "dead-end questions" detector (design report section 5.2/7): no
#: question log exists, and logging planner questions is itself inside the still-open
#: `fathm-plan-review-decision-planner-incentive-stance` hold's territory - it must not arrive as
#: a side effect of some other chunk.
ALL_DETECTORS = (
    detect_reason_code_issues,
    detect_repeated_waivers,
    detect_repeated_overrides,
    detect_gate_failure_hotspots,
    detect_profile_version_drift,
)


def run_all_detectors(scan: CorpusScan) -> list[Finding]:
    findings: list[Finding] = []
    for detector in ALL_DETECTORS:
        findings.extend(detector(scan))
    return findings
