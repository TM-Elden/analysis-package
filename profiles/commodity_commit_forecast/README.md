# Profile: commodity_commit_forecast / 0.1

First vertical profile under Analysis Package ap/0.2.

## Intent

Weekly (or cyclic) supplier-level commit / forecast packs for planning cells that explode demand, allocate suppliers, and net inventory - with human overrides labeled.

## Required output_contract entries (profile MUST)

- `supplier_forecast` (tabular)  
- `exception_list` (tabular)  
- `run_summary` (markdown or text)

## Expected engines (typical)

- bom_explode (deterministic)  
- allocate_suppliers (deterministic)  
- net_inventory (deterministic)  

Other engines allowed if declared.

## Reason codes (v0 allow-list)

- `HOLD_FOR_PRICE_NEGOTIATION`
- `LTA_LINEARITY_CAP`
- `SUPPLIER_RISK_SPLIT_CHANGE`
- `DATA_SNAPSHOT_CORRECTION`
- `NPI_BRIDGE_MANUAL`
- `OTHER` (requires reason_text)

## field_path grammar

`field_path_grammar.json` declares how `labels/overrides.jsonl` `field_path` segments map to
`supplier_forecast`'s key columns (`supplier`, `part`, `week`) + value column (`qty`) - see
`STANDARD.md`'s `field_path` note and `ap_gate.field_path.resolve_field_path`.

## Training-grade opt-in

`training_grade.json` ships with `require_reason_text` and `require_agent_draft` both `false` so this
reference profile stays representative of core (non-training-grade) usage - see `labels_row_shape` and
`agent_draft_present` in `product/CI-L1.md`.

## Example

See `../../examples/commodity-commit-v1/`.

## Out of profile

Location-derived thermal packs (AALC/valve trains) should use a different profile - do not force into rack BOM explode.
