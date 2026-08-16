"""Synthetic eval corpus for the C4 manager bot (P3.3's acceptance eval set).

Builds ~8 packages off `ap_agent_tools.reference_agent`'s own scaffolding (`package_create`), each
rewritten with a distinct supplier/part/override scenario so retrieval has real entities to
disambiguate between - then published and approved through the real `ap_review.ReviewWorkflow`
(not hand-inserted into the store) so the corpus is genuinely indexable exactly the way a real
package would be. One scenario is `confidentiality: internal_restricted` (the rest are the default
`internal`) so the corpus also exercises `ap_manager_bot.scoping`'s confidentiality tier.

Not a test module itself (no `test_` prefix) - imported by test_manager_bot_eval.py and
test_manager_bot_scoping.py so both suites see the identical corpus.
"""

from __future__ import annotations

import csv
import io
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
from ap_review.workflow import ReviewWorkflow
from ap_store.store import PackageStore

ANALYST = Identity(id="planner.corpus", roles=frozenset({Role.ANALYST}))
REVIEWER = Identity(id="lead.corpus", roles=frozenset({Role.REVIEWER}))


@dataclass(frozen=True)
class Scenario:
    label: str
    supplier: str
    part: str
    reason_code: str
    reason_text: str
    confidentiality: str = "internal"


#: 8 packages spanning distinct supplier/part/reason-code combinations - one confidentiality tier
#: apart (VAULT-TEC) for the scoping eval.
SCENARIOS: tuple[Scenario, ...] = (
    Scenario("acme_bbu", "ACME", "BBU-100", "HOLD_FOR_PRICE_NEGOTIATION", "Hold 300u off ACME pending Q4 price talks"),
    Scenario("globex_psu", "GLOBEX", "PSU-75", "LTA_LINEARITY_CAP", "Linearity cap binds weeks 38-40 per contract"),
    Scenario("initech_cap", "INITECH", "CAP-20", "SUPPLIER_RISK_SPLIT_CHANGE", "Shift 200u to secondary source after risk review"),
    Scenario("umbrella_relay", "UMBRELLA", "RELAY-40", "DATA_SNAPSHOT_CORRECTION", "Prior snapshot double-counted spares demand"),
    Scenario("wayne_bbu", "WAYNE", "BBU-200", "NPI_BRIDGE_MANUAL", "NPI bridge units not reflected in demand cut"),
    Scenario("stark_psu", "STARK", "PSU-90", "OTHER", "One-off customer expedite request, no standard code fits"),
    Scenario("wonka_cap", "WONKA", "CAP-55", "HOLD_FOR_PRICE_NEGOTIATION", "Cut 150u pending renegotiated unit price"),
    Scenario(
        "vaulttec_relay",
        "VAULT-TEC",
        "RELAY-99",
        "SUPPLIER_RISK_SPLIT_CHANGE",
        "Sole-source risk - splitting volume to a backup supplier",
        confidentiality="internal_restricted",
    ),
)


@dataclass
class Corpus:
    store: PackageStore
    index: IndexStore
    #: label -> published package_id, for eval questions to assert against.
    package_ids: dict[str, str]


def _rewrite_package(pkg_dir: Path, scenario: Scenario) -> None:
    manifest_path = pkg_dir / "MANIFEST.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["title"] = f"Weekly commodity commit pack - {scenario.supplier} {scenario.part} ({scenario.label})"
    manifest["confidentiality"] = scenario.confidentiality
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    override_id = f"ovr_{scenario.label}"
    field_path = f"supplier_forecast.{scenario.supplier}.{scenario.part}.week_36_qty"
    override_row = {
        "override_id": override_id,
        "field_path": field_path,
        "before": 1000,
        "after": 800,
        "reason_code": scenario.reason_code,
        "reason_text": scenario.reason_text,
        "bucket": 3,
        "evidence_refs": [f"inputs/supplier_splits.csv#rows=part:{scenario.part}"],
        "author": ANALYST.id,
        "ts": "2026-08-01T12:00:00Z",
    }
    (pkg_dir / "labels" / "overrides.jsonl").write_text(json.dumps(override_row) + "\n", encoding="utf-8")

    judgment_row = {
        "judgment_id": f"jdg_{scenario.label}",
        "claim": f"{scenario.supplier} {scenario.part} lead times are the main risk for this cycle",
        "confidence": "medium",
        "bucket": 2,
        "author": ANALYST.id,
        "ts": "2026-08-01T11:00:00Z",
        "applies_to": [f"supplier_forecast.{scenario.supplier}.*"],
    }
    (pkg_dir / "labels" / "judgments.jsonl").write_text(json.dumps(judgment_row) + "\n", encoding="utf-8")

    truth_row = {
        "rule_id": f"truth_{scenario.label}",
        "statement": f"{scenario.supplier} {scenario.part} is the primary planning line for this commodity family",
        "bucket": 3,
        "source": "sourcing_policy",
        "author": ANALYST.id,
        "ts": "2026-08-01T10:00:00Z",
    }
    (pkg_dir / "labels" / "truths_applied.jsonl").write_text(json.dumps(truth_row) + "\n", encoding="utf-8")

    exceptions_buf = io.StringIO()
    writer = csv.DictWriter(exceptions_buf, fieldnames=["exception_id", "supplier", "part", "week", "code", "detail"])
    writer.writeheader()
    writer.writerow(
        {
            "exception_id": f"ex_{scenario.label}",
            "supplier": scenario.supplier,
            "part": scenario.part,
            "week": "2026-W36",
            "code": scenario.reason_code,
            "detail": f"Override {override_id}: {scenario.reason_text}",
        }
    )
    (pkg_dir / "outputs" / "exceptions.csv").write_text(exceptions_buf.getvalue(), encoding="utf-8")

    forecast_buf = io.StringIO()
    writer = csv.DictWriter(forecast_buf, fieldnames=["supplier", "part", "week", "qty"])
    writer.writeheader()
    writer.writerow({"supplier": scenario.supplier, "part": scenario.part, "week": "2026-W36", "qty": 800})
    writer.writerow({"supplier": scenario.supplier, "part": scenario.part, "week": "2026-W37", "qty": 1000})
    (pkg_dir / "outputs" / "supplier_forecast.csv").write_text(forecast_buf.getvalue(), encoding="utf-8")

    run_summary = (
        f"# Run summary - {scenario.supplier} {scenario.part} commit pack\n\n"
        f"- **as_of:** 2026-08-01T12:00:00Z\n"
        f"- **Overrides applied:** 1 (see labels/overrides.jsonl)\n\n"
        f"## Notes\nSynthetic eval-corpus package for the C4 manager bot ({scenario.label})."
    )
    (pkg_dir / "outputs" / "RUN_SUMMARY.md").write_text(run_summary, encoding="utf-8")


def build_corpus(tmp_path: Path) -> Corpus:
    store = PackageStore(tmp_path / "store")
    index = IndexStore(tmp_path / "index")
    wf = ReviewWorkflow(store=store)
    package_ids: dict[str, str] = {}

    for scenario in SCENARIOS:
        pkg_dir = package_create(
            tmp_path / "pkgs" / scenario.label, title=scenario.label, analyst_id=ANALYST.id
        )
        _rewrite_package(pkg_dir, scenario)

        manifest = load_manifest(pkg_dir)
        record = store.publish(pkg_dir, actor=ANALYST)
        wf.transition(record.package_id, record.package_version, to_status="in_review", actor=ANALYST)
        record = wf.transition(record.package_id, record.package_version, to_status="approved", actor=REVIEWER)
        assert record.status == "approved"

        report = reindex_package(
            store=store, index=index, store_root=tmp_path / "store",
            package_id=record.package_id, package_version=record.package_version,
        )
        assert report is not None and not report.blocked, f"{scenario.label} failed to index: {report}"
        package_ids[scenario.label] = record.package_id
        assert manifest["confidentiality"] == scenario.confidentiality

    return Corpus(store=store, index=index, package_ids=package_ids)
