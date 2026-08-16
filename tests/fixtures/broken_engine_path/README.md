# Example Analysis Package (ap/0.2)

**Profile:** commodity_commit_forecast/0.1  
**Decisions:** D1A D2A D3C D4C D5A D6C D7A D8C (see `meta/ANALYSIS-PACKAGE-DECISIONS.md`)

Synthetic but realistic shape of a weekly BBU/PSU commodity commit pack under the formal agent-planner contract.

## Tree

```
ap-example-commodity-commit-v1/
  MANIFEST.yaml          # convenience manifest (compiles to RO-Crate later)
  GUIDELINE.md           # versioned method card
  inputs/                # pinned snapshots
  code/                  # deterministic entrypoint stub
  outputs/               # forecast + exceptions + summary
  labels/                # overrides, judgments, truths (jsonl)
  qa/checks.json         # gate results
```

## How an agent pair uses it
1. Create/open package for the cycle  
2. Refresh inputs with new snapshot_ids  
3. Run `python code/run_commit_pack.py --manifest MANIFEST.yaml`  
4. Human accepts/edits overrides in `labels/overrides.jsonl`  
5. `ap-gate check .` must pass before `qa.status: approved`  
6. Hand `outputs/` to consumers in `output_contract`

## Not production data
Hashes and quantities are demo placeholders.
