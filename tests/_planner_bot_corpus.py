"""Seeded fixture corpora for the `ap_planner_bot` detector tests (P4.2).

Mirrors `_manager_bot_corpus.py`'s pattern: scaffold real packages off
`ap_agent_tools.package_create`, rewrite a few fields, publish + approve through the real
`ap_review.ReviewWorkflow` (not hand-inserted into the store) so `scan_corpus` exercises the same
extract/rerun-gate path it does against a real store.

`gate_before_review=False` is used for both corpora here, deliberately: several of these packages
carry an intentionally-failing, unwaived check (the gate-failure-hotspot signal) that a real team
would only reach `approved` for under that policy override (documented as a deliberate override in
`ap_review/policy.py`, not a silent bypass) - or, in practice, a check that used to pass and only
started failing after a later Standard change. Either way `scan_corpus` must cope with an approved
package that currently fails the gate; that's exactly what the hotspot detector looks for.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from ap_agent_tools.tools import package_create
from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_gate.load_manifest import load_manifest
from ap_index.index_store import IndexStore
from ap_index.reindex import reindex_package
from ap_review.policy import ReviewPolicy
from ap_review.workflow import ReviewWorkflow
from ap_store.store import PackageStore

ANALYST = Identity(id="planner.drift-fixture", roles=frozenset({Role.ANALYST}))
REVIEWER = Identity(id="lead.drift-fixture", roles=frozenset({Role.REVIEWER}))

#: field_path/reason_code pair repeated across REPEATED_OVERRIDE packages, feeding
#: detect_repeated_overrides.
REPEATED_FIELD_PATH = "supplier_forecast.ACME.BBU-100.week_36_qty"
REPEATED_REASON_CODE = "HOLD_FOR_PRICE_NEGOTIATION"

#: OTHER reason_text repeated across OTHER_THEME packages, feeding detect_reason_code_issues'
#: OTHER-heavy branch.
OTHER_THEME_TEXT = "Recurring one-off customer expedite pattern, no standard code fits"

#: reason_code not present in the commodity_commit_forecast profile's allow-list, feeding
#: detect_reason_code_issues' unknown-code branch.
UNKNOWN_REASON_CODE = "BOGUS_CODE_NOT_IN_ALLOWLIST"


@dataclass(frozen=True)
class DriftScenario:
    label: str
    field_path: str
    reason_code: str
    reason_text: str = ""
    waive_engines: bool = False  # feeds detect_repeated_waivers
    break_guideline: bool = False  # feeds detect_gate_failure_hotspots
    profile_version: str | None = None  # feeds detect_profile_version_drift


#: 9 packages: 3 repeated-override, 3 OTHER-theme (also the gate-failure-hotspot packages), 2
#: unknown-code, plus the waiver signal riding on the first 3 (repeated-override) packages. See
#: module docstring for why waiver + hotspot packages need gate_before_review=False.
DRIFT_SCENARIOS: tuple[DriftScenario, ...] = (
    DriftScenario("ovr_a", REPEATED_FIELD_PATH, REPEATED_REASON_CODE, waive_engines=True),
    DriftScenario("ovr_b", REPEATED_FIELD_PATH, REPEATED_REASON_CODE, waive_engines=True),
    DriftScenario("ovr_c", REPEATED_FIELD_PATH, REPEATED_REASON_CODE, waive_engines=True),
    DriftScenario("other_a", "supplier_forecast.STARK.PSU-90.week_36_qty", "OTHER", OTHER_THEME_TEXT, break_guideline=True),
    DriftScenario("other_b", "supplier_forecast.WAYNE.PSU-90.week_36_qty", "OTHER", OTHER_THEME_TEXT, break_guideline=True),
    DriftScenario("other_c", "supplier_forecast.WONKA.PSU-90.week_36_qty", "OTHER", OTHER_THEME_TEXT, break_guideline=True),
    DriftScenario("unknown_a", "supplier_forecast.GLOBEX.CAP-20.week_36_qty", UNKNOWN_REASON_CODE),
    DriftScenario("unknown_b", "supplier_forecast.INITECH.CAP-20.week_36_qty", UNKNOWN_REASON_CODE),
    DriftScenario("version_drift", "supplier_forecast.UMBRELLA.RELAY-40.week_36_qty", REPEATED_REASON_CODE, profile_version="9.9"),
)

#: A clean corpus with no injected drift: distinct field_path/reason_code per package, no
#: waivers, nothing broken, all default profile version - the sweep must find nothing here.
CLEAN_SCENARIOS: tuple[DriftScenario, ...] = (
    DriftScenario("clean_a", "supplier_forecast.ACME.BBU-100.week_36_qty", "HOLD_FOR_PRICE_NEGOTIATION"),
    DriftScenario("clean_b", "supplier_forecast.GLOBEX.PSU-75.week_36_qty", "LTA_LINEARITY_CAP"),
    DriftScenario("clean_c", "supplier_forecast.INITECH.CAP-20.week_36_qty", "SUPPLIER_RISK_SPLIT_CHANGE"),
)


def _rewrite_package(pkg_dir: Path, scenario: DriftScenario) -> None:
    manifest_path = pkg_dir / "MANIFEST.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    if scenario.profile_version:
        manifest["profile"] = f"commodity_commit_forecast/{scenario.profile_version}"

    if scenario.waive_engines:
        # Break engines[0]'s path so engines_pinned genuinely fails without the waiver, then
        # waive it - mirrors tests/test_waiver_order_and_path_containment.py's fixture pattern.
        manifest["engines"][0]["path"] = "code/does_not_exist.py"
        manifest.setdefault("qa", {})["waivers"] = [
            {"check_id": "engines_pinned", "reason": f"tracked gap ({scenario.label})"}
        ]

    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    if scenario.break_guideline:
        (pkg_dir / "GUIDELINE.md").unlink(missing_ok=True)

    override_row = {
        "override_id": f"ovr_{scenario.label}",
        "field_path": scenario.field_path,
        "before": 1000,
        "after": 800,
        "reason_code": scenario.reason_code,
        "reason_text": scenario.reason_text,
        "author": ANALYST.id,
        "ts": "2026-08-01T12:00:00Z",
        # The template's model_run.role declares agent participation, so agent_draft_present
        # would otherwise advisory-fail on every package here - noise unrelated to what each
        # scenario is testing. Carry it on every row so that signal stays off unless a scenario
        # deliberately wants it (none currently do).
        "agent_draft": {"reason_code": scenario.reason_code, "reason_text": scenario.reason_text or "n/a"},
    }
    (pkg_dir / "labels" / "overrides.jsonl").write_text(json.dumps(override_row) + "\n", encoding="utf-8")


def _build(
    tmp_path: Path, scenarios: tuple[DriftScenario, ...], name: str, *, index: IndexStore | None = None
) -> PackageStore:
    store_root = tmp_path / f"{name}-store"
    store = PackageStore(store_root)
    wf = ReviewWorkflow(store=store, policy=ReviewPolicy(gate_before_review=False))

    for scenario in scenarios:
        pkg_dir = package_create(
            tmp_path / f"{name}-pkgs" / scenario.label, title=scenario.label, analyst_id=ANALYST.id
        )
        _rewrite_package(pkg_dir, scenario)
        load_manifest(pkg_dir)  # sanity: still parses after rewrite

        record = store.publish(pkg_dir, actor=ANALYST)
        wf.transition(record.package_id, record.package_version, to_status="in_review", actor=ANALYST)
        record = wf.transition(record.package_id, record.package_version, to_status="approved", actor=REVIEWER)
        assert record.status == "approved"

        if index is not None:
            report = reindex_package(
                store=store, index=index, store_root=store_root,
                package_id=record.package_id, package_version=record.package_version,
            )
            assert report is not None and not report.blocked, f"{scenario.label} failed to index: {report}"

    return store


def build_drift_corpus(tmp_path: Path) -> PackageStore:
    return _build(tmp_path, DRIFT_SCENARIOS, "drift")


def build_clean_corpus(tmp_path: Path) -> PackageStore:
    return _build(tmp_path, CLEAN_SCENARIOS, "clean")


def build_drift_corpus_with_index(tmp_path: Path) -> tuple[PackageStore, IndexStore]:
    """Same drift corpus as `build_drift_corpus`, plus a populated `IndexStore` - for the C6
    drafting-service tests (`test_planner_bot_service.py`/`test_planner_bot_sweep.py`), which need
    redacted evidence chunks to fetch, not just the scan/detector layer `build_drift_corpus` alone
    is enough for."""
    index = IndexStore(tmp_path / "drift-idx-index")
    store = _build(tmp_path, DRIFT_SCENARIOS, "drift-idx", index=index)
    return store, index


def build_clean_corpus_with_index(tmp_path: Path) -> tuple[PackageStore, IndexStore]:
    index = IndexStore(tmp_path / "clean-idx-index")
    store = _build(tmp_path, CLEAN_SCENARIOS, "clean-idx", index=index)
    return store, index
