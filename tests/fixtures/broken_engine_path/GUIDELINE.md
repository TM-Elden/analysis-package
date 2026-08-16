# Commodity commit / forecast pack - guideline
**guideline_version:** commodity-commit-guideline@1.2.0  
**profile:** commodity_commit_forecast/0.1  
**standard:** ap/0.2

## Purpose
Weekly supplier-level quantities for assigned power commodities (example: BBU, BBU shelf, PSU, PSU shelf).

## Output contract
1. `supplier_forecast.csv` - qty by supplier × part × week (13 weeks)
2. `exceptions.csv` - rows needing human attention
3. `RUN_SUMMARY.md` - short narrative for archive

## Method (deterministic path)
1. Load pinned inputs from `inputs/` (manifest snapshot_ids).
2. `bom_explode` - rack demand → component demand via BOM.
3. Add independent demand (spares/NPI) from pinned file.
4. `allocate_suppliers` - apply split rules.
5. `net_inventory` - on-hand + open PO netting policy per GUIDELINE section "Netting".
6. Write engine outputs to a temp table.
7. Apply `labels/overrides.jsonl` in order.
8. Emit final outputs + exception heuristics.

## Agent pair rules (mandatory)
- MUST open/update this package before changing outputs.
- MUST NOT leave numeric edits only in Excel without an override row.
- Model MAY propose overrides; human or explicit accept writes `labels/overrides.jsonl`.
- Model MUST NOT replace bom_explode / allocate / net engines.
- Refuse `qa.status: approved` until ap-gate passes.

## Netting (summary)
- Prefer supply already on PO before new commit request, by part, then supplier affinity rules in `supplier_splits.csv`.

## Exceptions that stay outside this pack type
Location-derived thermal gear (AALC / valve trains) uses a **different pack type** - do not force into rack BOM explode. See inversion essay / separate profile later.

## Reason codes allowed (v1.1 excerpt)
- `HOLD_FOR_PRICE_NEGOTIATION`
- `LTA_LINEARITY_CAP`
- `SUPPLIER_RISK_SPLIT_CHANGE`
- `DATA_SNAPSHOT_CORRECTION`
- `NPI_BRIDGE_MANUAL`
- `OTHER` (requires reason_text)

## QA
Run: `ap-gate check .` (CLI; agents call the same entrypoint).
