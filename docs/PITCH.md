# Pitch - fathm

**Date:** 2026-08-16  
**Status:** Internal joint project draft  
**Product name:** **fathm** *(v.)* - to understand something fully, down to its source.  
**Format:** Analysis Package (`ap/0.2`)

> Understand every analysis fully, down to its source.  
> Powered by the Analysis Package standard.

---

## Hook

Every company doing data analysis has the same hidden liability: nobody can reliably trace a conclusion back to the data and method that produced it. As AI agents generate more of that analysis, the liability compounds - because the analyst you cannot audit may not even be human.

**fathm** exists so every published analysis can be understood fully - down to its source.

## Why now

Two unlocks landed together:

1. **Agents** are already drafting finance, ops, and forecast analysis inside real teams.  
2. **Standards + CI** can finally attach to the *unit of publish* (not only warehouse tables) - and LLMs make a later layer of *semantic* review possible.

Schema CI could always check "is there a methodology field." Structural provenance packages were always possible but rarely enforced on Excel-era planning. Agent publish volume makes enforcement urgent. LLM semantic review is **phase two**, not the pilot's only bar.

## Wedge

**Finance, ops, and forecasting teams publishing analysis via AI agents** - where provenance is already a compliance or executive trust requirement and the pain is acute.

Not "all data analysis." A narrow, budget-holding buyer.

**Works with agent + Excel as UI.** The Analysis Package is the publish artifact - not a demand to abandon spreadsheets on day one.

## How it works

| # | Layer | Role | Pilot? |
|---|--------|------|--------|
| 1 | **Standard (AP)** | Opinionated core schema for what a package must contain (data, method, provenance, human deltas, QA). Pack-type **profiles** extend the core - customers do not redesign MUST fields. | Yes |
| 2 | **L1 CI (fathm gate)** | Every published package validated structurally; non-conforming packages flagged/blocked. | Yes |
| 3 | **L2 Semantic CI** | LLM-assisted flags: does the write-up follow the package evidence? | After L1 |
| 4 | **Team Model** | Per-customer model/RAG over *their* validated corpus; management Q&A. | After corpus exists |
| 5 | **Planner Model + HITL** | Reasons across corpus + CI flags; proposes Standard/profile changes; human owner approves. | Later tier |

## Default Standard (not vapor)

The opinionated default is **Analysis Package ap/0.2** in this repo:

- Portable directory + RO-Crate profile path  
- Pinned inputs, versioned method, deterministic engines  
- Overrides/judgments/truths as labels (jsonl)  
- Completeness gate semantics  
- First profile: **commodity commit / forecast** (finance/ops adjacent; expandable to FP&A flash)

See `standard/ap-0.2/STANDARD.md` and `examples/commodity-commit-v1/`.

## Moat

Not the software alone - a well-funded competitor can clone schema-and-CI. The moat is the **proprietary, standardized, provenance-tagged corpus and conformance behavior** that only accumulates by running the fathm pipeline over real customer usage.

Software is the wedge that earns the data; the data (and structure-level learning under trust constraints) is the long-term asset. Closer to Bloomberg/Palantir position defense than typical point SaaS.

## Business model - one primary path

**Primary:** SaaS from day one - fathm Standard tooling + L1 CI + (later) Team Model. Real, fundable revenue.

As corpus compounds **within** a customer (and structure-level patterns across customers under trust rules), Planner Model and pattern learning become the differentiated upgrade tier - not a separate business.

**Services** (implementation) are a funding bridge for early enterprise onboarding and design partners - not a pitched pillar.

## Trust answer (decided, not open)

Contractual stance:

- Train only on **structure and conformance behavior** (how packages get flagged and fixed)  
- **Never** on underlying business content for any cross-customer model  
- **Never** pool one customer's content into a model resold to another  
- Per-customer Team Models stay isolated to that customer instance  

This is the only stance that lets us sell to competitors in the same industry without an immediate veto.

## Traction plan (next 90 days)

Ship **Analysis Package Standard + fathm L1 CI** for one pack type (start: commodity commit / forecast or partner's closest equivalent) with **1 design-partner team**.

**Success bar:**

- Structural CI-flagged packages drop by a pre-agreed % over 4-6 weeks  
- **100% of published packages** carry complete, queryable provenance - vs ~0% baseline today  

Smallest provable claim:

> Packages published under the Standard have complete, queryable provenance; packages published without it do not.

Team Model, Planner Model, and data moat narrative are **sequenced after** this proves out - not part of the 90-day must-hit SKU.

## Market size (directional only)

Adjacent data governance / data quality software is a multi-billion category and growing. We are **not** selling classic data governance. We are the **AI-native layer for provenance on AI-assisted analysis publish** - a wedge inside that spend.

**No placeholder citations in external materials until verified.** Bottoms-up SAM (target accounts × ACV) is a tracked open item before any external fundraise pitch.

## The ask

Seeking **one design-partner** - a finance or ops analytics team already using AI agents for reporting/planning - to pilot fathm (Standard + L1 CI) over one quarter.

Capital follows proof. Not opening a funding conversation until the pilot shows the flag-rate / audit-completeness result above.

## Still open (tracked, not blocking pilot design)

- Bottoms-up TAM/SAM for the finance/ops-analytics wedge  
- Standard versioning/migration strategy as profiles evolve  
- Final in-customer HITL authority model (who approves Standard/profile changes)  
- Domain / GH org under the fathm mark  

## Naming history

| Version | Name |
|---------|------|
| pitch-v2.pdf | [Working Name] |
| joint repo v1 | Analysis Package (product + format collapsed) |
| **locked** | **fathm** (product) + **Analysis Package** (format) |

Source PDF retained at `research/pitch-v2-source.pdf`. Brand file: `docs/BRAND.md`.
