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

## Example

See `../../examples/commodity-commit-v1/`.

## Out of profile

Location-derived thermal packs (AALC/valve trains) should use a different profile - do not force into rack BOM explode.
