#!/usr/bin/env python3
"""Seed a small, realistic, pre-approved background corpus for the fathm core demo.

Design context: `data/fathm-core-demo/report.md` in the firstmate repo. The core demo's own live
package (the one `tom.planner` authors during the demo itself, ACME/BBU-100) is created fresh
during the demo and must stay out of this script entirely - this script only seeds *history* the
manager's console/index already has behind it before the demo starts, so the review queue,
package list, and search index don't look freshly-born on demo day.

## What this creates

7 packages, profile `commodity_commit_forecast/0.1`, scaffolded from the same gold template
`ap_agent_tools.package_create` uses (the pattern `tests/_manager_bot_corpus.py` and
`tests/_planner_bot_corpus.py` already follow - read those first if extending this). Each package:

- A distinct fictional supplier/part (Vertex Circuits, NorthStar Metals, Solara Components, Kestrel
  Fabrication, Brightline Industrial, Meridian Alloys, Cobalt Ridge Electronics - all invented,
  none overlapping the live demo's ACME/BBU-100 story).
- Spread across weeks 2026-W30 through 2026-W36 (`as_of`), so the corpus reads as several weeks of
  real operating history, not one story repeated.
- Authored by one of two distinct analyst identities (`tom.planner`, `priya.planner`) - not one
  person authoring everything.
- One realistic override recorded through `ap_mcp.tools.override_record` (the exact tool/row shape
  a live MCP call produces - not a hand-built dict), with a valid `reason_code` drawn from the
  profile's `reason_codes.json` allow-list, spread across several different codes rather than
  repeating one.
- Driven through the real `draft -> in_review -> approved` transitions via
  `ap_review.ReviewWorkflow` (reviewed/approved by `mia.manager`), then redacted + indexed via
  `ap_index.reindex.reindex_package` - so the audit trail, redaction sidecar, and FTS5 index are
  genuinely populated, not hand-inserted rows.

The three identities (`tom.planner` / `priya.planner`, roles `analyst`; `mia.manager`, role
`reviewer`) are provisioned in the auth DB if not already present (`--no-password`, matching the
core-demo runbook's planner-identity convention - these are for the background corpus, not the
demo's own login flow).

## Usage

    AP_STORE_ROOT=~/.fathm-demo/ap_store \\
    AP_INDEX_ROOT=~/.fathm-demo/ap_index \\
    AP_AUTH_DB=~/.fathm-demo/auth.sqlite3 \\
    PYTHONPATH=src python3 scripts/seed_demo_corpus.py

Env vars follow the same `AP_STORE_ROOT`/`AP_INDEX_ROOT`/`AP_AUTH_DB` convention every other entry
point in this repo uses (`ap_api.deps`, `ap_planner_bot.sweep`, `ap_auth.cli`) - defaulting to
`~/.fathm/...` if unset, same as those. Point them at the demo's own scratch roots (e.g.
`~/.fathm-demo/*`), never at a real store, and *never* at the gold-pack fixture
(`examples/commodity-commit-v1`) - this script only ever writes into scratch package directories
under a temp dir, so the fixture is untouched regardless.

## Idempotency

Each seeded package's `package_id` is deterministic (`pkg_demo_seed_<label>`, not a random uuid),
so a second run recognizes a package already present via `PackageStore.get(package_id)` and skips
it entirely rather than duplicating or erroring - safe to re-run against the same roots any number
of times. User provisioning is likewise idempotent (an `AuthError: user already exists` is caught
and treated as already-provisioned).

## Verification

The script prints one line per package (`[seeded]`/`[skipped, already present]`) plus a final
summary asserting all 7 packages are `approved`, gate-`pass`, and discoverable in the FTS5 index
(a live `index.search(...)` call per package, not an assumption) - exits non-zero if any check
fails. See `tests/test_seed_demo_corpus.py` for the same assertions run against a scratch root as
part of the test suite (including the re-run-is-a-no-op case).
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ap_agent_tools.tools import package_check as _package_check
from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_auth.store import AuthError, AuthStore, DEFAULT_AUTH_DB
from ap_gate.load_manifest import load_manifest
from ap_index.index_store import IndexStore
from ap_index.reindex import reindex_package
from ap_mcp.tools import override_record as _override_record
from ap_mcp.tools import package_create as _package_create
from ap_review.workflow import ReviewWorkflow
from ap_store.store import PackageStore, StoreError

#: Same local-first default/override convention as ap_api.deps.DEFAULT_STORE_ROOT/DEFAULT_INDEX_ROOT
#: and ap_planner_bot.sweep's own copy of it - resolved independently here so this script has no
#: dependency on the interface layer.
DEFAULT_STORE_ROOT = Path(os.environ.get("AP_STORE_ROOT", str(Path.home() / ".fathm" / "ap_store")))
DEFAULT_INDEX_ROOT = Path(os.environ.get("AP_INDEX_ROOT", str(Path.home() / ".fathm" / "ap_index")))

TOM = Identity(id="tom.planner", roles=frozenset({Role.ANALYST}))
PRIYA = Identity(id="priya.planner", roles=frozenset({Role.ANALYST}))
MIA = Identity(id="mia.manager", roles=frozenset({Role.REVIEWER}))

VALID_REASON_CODES = (
    "HOLD_FOR_PRICE_NEGOTIATION",
    "LTA_LINEARITY_CAP",
    "SUPPLIER_RISK_SPLIT_CHANGE",
    "DATA_SNAPSHOT_CORRECTION",
    "NPI_BRIDGE_MANUAL",
)


@dataclass(frozen=True)
class Scenario:
    label: str
    supplier: str
    part: str
    week: str  # ISO week, e.g. "2026-W30"
    as_of: str  # ISO 8601 timestamp
    analyst: Identity
    reason_code: str
    before_qty: int
    after_qty: int
    reason_text: str


#: 7 packages spanning weeks 2026-W30..W36, two analysts, five distinct reason codes, seven
#: distinct fictional supplier/part pairs - none overlapping the live demo's ACME/BBU-100 story.
SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "vertex_relay30", "Vertex Circuits", "RLY-410", "2026-W30", "2026-07-25T09:00:00Z", TOM,
        "HOLD_FOR_PRICE_NEGOTIATION", 3000, 2600,
        "Holding 400u off Vertex Circuits pending Q3 unit-price renegotiation.",
    ),
    Scenario(
        "northstar_bus31", "NorthStar Metals", "BUSBAR-22", "2026-W31", "2026-08-01T09:00:00Z", PRIYA,
        "LTA_LINEARITY_CAP", 5400, 5000,
        "LTA linearity cap binds this cycle per the NorthStar Metals long-term agreement.",
    ),
    Scenario(
        "solara_cap32", "Solara Components", "CAP-330", "2026-W32", "2026-08-08T09:00:00Z", TOM,
        "SUPPLIER_RISK_SPLIT_CHANGE", 1800, 1500,
        "Splitting 300u to a secondary source after a Solara Components risk review flagged single-site exposure.",
    ),
    Scenario(
        "kestrel_conn33", "Kestrel Fabrication", "CONN-88", "2026-W33", "2026-08-15T09:00:00Z", PRIYA,
        "DATA_SNAPSHOT_CORRECTION", 2200, 2450,
        "Prior demand snapshot undercounted spares pull for Kestrel Fabrication connectors; corrected upward.",
    ),
    Scenario(
        "brightline_reg34", "Brightline Industrial", "REG-15", "2026-W34", "2026-08-22T09:00:00Z", TOM,
        "NPI_BRIDGE_MANUAL", 900, 1200,
        "NPI bridge units for the new Brightline Industrial regulator not reflected in the automated demand cut.",
    ),
    Scenario(
        "meridian_wire35", "Meridian Alloys", "WIRE-06", "2026-W35", "2026-08-29T09:00:00Z", PRIYA,
        "HOLD_FOR_PRICE_NEGOTIATION", 6100, 5700,
        "Holding 400u off Meridian Alloys pending renegotiated wire-stock pricing.",
    ),
    Scenario(
        "cobalt_sensor36", "Cobalt Ridge Electronics", "SENSOR-71", "2026-W36", "2026-09-05T09:00:00Z", TOM,
        "SUPPLIER_RISK_SPLIT_CHANGE", 4000, 3600,
        "Splitting volume away from Cobalt Ridge Electronics after a sole-source risk flag this cycle.",
    ),
)

assert len(SCENARIOS) == 7
assert {s.analyst.id for s in SCENARIOS} == {"tom.planner", "priya.planner"}
assert len({s.reason_code for s in SCENARIOS}) >= 4
for _s in SCENARIOS:
    assert _s.reason_code in VALID_REASON_CODES, _s.reason_code


def _package_id_for(label: str) -> str:
    return f"pkg_demo_seed_{label}"


def _ensure_users(auth_db: Path) -> None:
    with AuthStore(auth_db) as store:
        for identity, display_name, role in (
            (TOM, "Tom Planner", Role.ANALYST),
            (PRIYA, "Priya Planner", Role.ANALYST),
            (MIA, "Mia Manager", Role.REVIEWER),
        ):
            try:
                store.create_user(
                    identity.id, display_name=display_name, roles=frozenset({role}), password=None
                )
                print(f"[user] created {identity.id!r} (role: {role.value})")
            except AuthError:
                print(f"[user] {identity.id!r} already provisioned - skipping")


def _indexed(index: IndexStore, package_id: str, part: str) -> bool:
    hits = index.search(part, filters=None)
    return any(h.chunk.package_id == package_id for h in hits)


def _seed_one(
    scenario: Scenario, *, store: PackageStore, index: IndexStore, store_root: Path, workdir: Path
) -> str:
    """Create, override, gate-check, publish, review, approve, and index one scenario package.
    Returns the package_id. Idempotent: a package_id already present in the store is left
    untouched and its existing status is verified instead of re-seeding."""
    package_id = _package_id_for(scenario.label)
    existing = store.get(package_id)
    if existing is not None:
        assert existing.status == "approved", (
            f"{package_id} already exists but is status={existing.status!r}, not approved - "
            "a previous partial seed run may have left the store in a bad state"
        )
        if not _indexed(index, package_id, scenario.part):
            # A prior run committed the approval but never completed indexing (e.g. reindex_package
            # raised after the status CAS above already landed) - repair it now rather than silently
            # skipping, since reindex_package is idempotent (redact + index for an already-approved
            # package) and skipping here would leave the corpus approved-but-unsearchable forever.
            print(f"[repairing] {package_id} is approved but missing from the FTS5 index - reindexing")
            redaction_report = reindex_package(
                store=store, index=index, store_root=store_root,
                package_id=package_id, package_version=existing.package_version,
            )
            assert redaction_report is not None and not redaction_report.blocked, (
                f"{package_id} was blocked from indexing: {redaction_report}"
            )
            assert _indexed(index, package_id, scenario.part), (
                f"{package_id} still not found in the FTS5 index for query {scenario.part!r} "
                "after reindexing"
            )
        print(f"[skipped, already present] {package_id} ({scenario.supplier} {scenario.part})")
        return package_id

    pkg_dir = workdir / scenario.label
    field_path = f"supplier_forecast.{scenario.supplier.replace(' ', '_')}.{scenario.part}.{scenario.week.replace('-', '_')}_qty"

    pkg_dir = Path(
        _package_create(
            dest_dir=str(pkg_dir),
            title=f"Commodity commit pack - {scenario.supplier} {scenario.part} ({scenario.week})",
            analyst_id=scenario.analyst.id,
            as_of=scenario.as_of,
        )
    )

    _override_record(
        package_dir=str(pkg_dir),
        field_path=field_path,
        before=scenario.before_qty,
        after=scenario.after_qty,
        reason_code=scenario.reason_code,
        draft_reason_text=scenario.reason_text,
    )

    report = _package_check(pkg_dir)
    assert report["overall"] == "pass", f"{package_id} failed the gate: {report}"

    # Manifest carries the deterministic package_id, not the random uuid package_create scaffolded
    # - rewritten directly, mirroring the same pattern tests/_manager_bot_corpus.py's
    # _rewrite_package uses for its own generated corpus.
    manifest = load_manifest(pkg_dir)
    manifest["package_id"] = package_id
    manifest_path = pkg_dir / "MANIFEST.yaml"
    import yaml

    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    record = store.publish(pkg_dir, actor=scenario.analyst)
    assert record.package_id == package_id

    wf = ReviewWorkflow(store=store)
    wf.transition(package_id, record.package_version, to_status="in_review", actor=scenario.analyst)
    record = wf.transition(package_id, record.package_version, to_status="approved", actor=MIA)
    assert record.status == "approved"

    redaction_report = reindex_package(
        store=store, index=index, store_root=store_root,
        package_id=package_id, package_version=record.package_version,
    )
    assert redaction_report is not None and not redaction_report.blocked, (
        f"{package_id} was blocked from indexing: {redaction_report}"
    )

    assert _indexed(index, package_id, scenario.part), (
        f"{package_id} approved and reindexed but not found in the FTS5 index for query {scenario.part!r}"
    )

    print(f"[seeded] {package_id} ({scenario.supplier} {scenario.part}, {scenario.week}, {scenario.reason_code})")
    return package_id


def seed_demo_corpus(*, store_root: Path, index_root: Path, auth_db: Path) -> list[str]:
    """Seed all 7 scenarios into the given roots (creating them if needed). Returns the list of
    package_ids. Safe to call repeatedly against the same roots."""
    _ensure_users(auth_db)

    package_ids: list[str] = []
    with tempfile.TemporaryDirectory(prefix="fathm-demo-seed-") as tmp, PackageStore(store_root) as store, IndexStore(
        index_root
    ) as index:
        workdir = Path(tmp)
        for scenario in SCENARIOS:
            package_ids.append(
                _seed_one(scenario, store=store, index=index, store_root=store_root, workdir=workdir)
            )

        # Final verification pass: every package approved, gate-pass at publish time, and
        # discoverable in the index - asserted programmatically, not assumed from the loop above
        # (the loop's own skip branch repairs indexing gaps, but this pass re-confirms the outcome
        # for every package regardless of which branch produced it).
        assert len(package_ids) == 7
        for scenario, package_id in zip(SCENARIOS, package_ids):
            record = store.get(package_id)
            assert record is not None and record.status == "approved", package_id
            assert record.gate_overall == "pass", package_id
            assert _indexed(index, package_id, scenario.part), (
                f"{package_id} approved but not found in the FTS5 index for query {scenario.part!r}"
            )

    return package_ids


def main() -> int:
    store_root = DEFAULT_STORE_ROOT
    index_root = DEFAULT_INDEX_ROOT
    auth_db = Path(os.environ.get("AP_AUTH_DB", str(DEFAULT_AUTH_DB)))

    print(f"Seeding fathm demo corpus into store={store_root} index={index_root} auth_db={auth_db}")
    package_ids = seed_demo_corpus(store_root=store_root, index_root=index_root, auth_db=auth_db)
    print(f"Done: {len(package_ids)} approved, gate-passing, indexed packages in the corpus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
