# Architecture - Standard + Product

## One project, two surfaces

| Surface | Audience | Artifact |
|---------|----------|----------|
| **Standard (AP)** | Agents, planners, auditors, integrators | Package format + profiles + gate semantics |
| **Product** | Design partners, later customers | Hosted CI, corpus, Team/Planner models |

The Standard is open-spec oriented. The Product earns a data moat by running the Standard over real publish cycles.

```
                    ┌─────────────────────────────┐
                    │   Human planner + Agent     │
                    └─────────────┬───────────────┘
                                  │ emits
                                  v
                    ┌─────────────────────────────┐
                    │     Analysis Package        │
                    │  inputs · method · engines  │
                    │  labels · outputs · QA      │
                    └─────────────┬───────────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              v                   v                   v
        L1 Structural CI    L2 Semantic CI      Consumers
        (schema, pins,      (LLM: does claim    (sourcing, finance,
         unlabeled diff)     follow data?)       audit, train-opt-in)
              │                   │
              └─────────┬─────────┘
                        v
              Validated publish corpus
                        │
              ┌─────────┴─────────┐
              v                   v
         Team Model          Planner Model
         (per-tenant RAG)    (proposes Standard
                              changes + HITL)
```

## CI levels (do not conflate)

### L1 - Structural gate (pilot MVP)

Machine-checkable, no LLM required:

- MUST fields present  
- output_contract files exist  
- inputs pinned (snapshot_id / hash or external_ref)  
- deterministic engines version-pinned  
- numeric drift vs engine replay ⊆ overrides.jsonl  
- reason_codes in allow-list  
- qa.status honest  

**This is `ap-gate`.** Non-conforming packages are flagged / blocked from "published."

### L2 - Semantic review (after L1)

LLM-assisted checks, default **flag not hard-block** until calibrated:

- Does the written conclusion follow from declared outputs + labels?  
- Are confidence / judgment claims labeled as judgment?  
- Missing evidence refs on material overrides?

Pitch "why now" (LLMs can check reasoning) lives primarily in **L2**. Do not promise L2 as the day-one pilot bar.

## Standard mapping to package

| Product language | Standard field / path |
|------------------|----------------------|
| Data | `inputs[]` + files under `inputs/` |
| Methodology | `method` + `GUIDELINE.md` + `engines[]` |
| Provenance | snapshot_id, as_of, hashes, PROV/RO-Crate, owners |
| Confidence / human deltas | `labels/judgments.jsonl`, overrides with reason_code |
| Publish gate | `qa/` + L1 CI |
| Training policy | `training_eligibility` (default false) |

## Profiles

Core Standard is process-shaped. Domain shape is a **profile**:

- `profiles/commodity_commit_forecast/` - first profile  
- Future: exception/aging, FP&A flash, demand consensus  

Customers extend via profiles + reason_code sets - they do not redesign the MUST core.

## Agent obligation

Planning agents that pair with humans MUST treat the package as the system of record for the cycle. Chat is ephemeral UI. Excel may remain interactive UI; exports + labels still land in the package.

## Pilot scope (90 days) - in / out

**In**

- Default Standard (ap/0.2) + commodity_commit_forecast profile  
- L1 CI enforcement on publish  
- 1 design-partner team  
- Success: published packages have complete queryable provenance (vs ~0% baseline); structural flag rate trends down  

**Out of pilot commit**

- Team Model as required SKU  
- Planner Model  
- Hard L2 semantic blocking  
- Multi-tenant corpus learning  

## Moat (honest)

Software (schema + CI) is copyable. Defensibility is the **standardized, provenance-tagged corpus and conformance patterns** earned only by running the pipeline on real customer publish traffic - under the trust stance (structure/conformance only for any pooled learning; content never cross-customer).

## Trust stance

See [product/TRUST.md](../product/TRUST.md).
