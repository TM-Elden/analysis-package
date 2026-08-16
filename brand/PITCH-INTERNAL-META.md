# fathm - internal Meta pilot pitch (primary path)

**Audience:** Meta manager / pilot team lead / partner eng  
**Posture:** Less risk, less reward - build as internal tool first  
**Public company narrative:** secondary (`brand/PITCH-YC.md`)

---

## One-liner

**fathm** - every AI-assisted analysis published as a complete package you can gate and query down to its source.

---

## Problem (internal)

- Bots and agents draft analysis faster than review  
- Leadership asks "where did this number come from?" and the answer is a thread or a sheet  
- No shared unit of publish: method, inputs-as-of, and human overrides are tribal  

## Solution

1. **Analysis Package** - standard folder of inputs, method, outputs, labels (judgment), QA  
2. **Gate** - won't count as published until complete  
3. **Chart room** - managers query the team's validated packages with citations  
4. **HITL on standard** - when the rules change, a human approves  

## Why me

- Supply-chain planner who lived untraceable spreadsheets  
- Engineer / AI builder who can ship the loop  
- Ops doctrine (soundings): don't commit without a measurement  

## Why not wait for a platform team / ERP

Focused publish-layer wins faster than monolith features (same reason planning modules beat suite planning). We need a **unit of analysis publish**, not another lake catalog.

## Pilot ask

| Need | Why |
|------|-----|
| One pilot team (finance or planning-adjacent) | Real packages |
| Manager sponsor | Air cover + chart room user |
| 90 days | Prove habit |
| Access to current publish workflow | Meet people where they work (Excel/agent OK) |

**Not asking:** headcount cuts, company-wide mandate day one, public blog about Meta internals.

## Success (90 days)

1. **100%** of in-scope publishes are packages with queryable provenance  
2. Sponsor uses chart room **weekly**  
3. Planners report less rebuild / clearer credit on overrides  
4. Written decision: expand, hand off, or stop  

## Trust / policy

- Follow Meta data and AI use policies  
- No external training on Meta content via public tools  
- Synthetic examples only in any public repo  

## Relationship to public `ap` standard

Public Analysis Package work is the **portable craft**. Internal schemas may extend with Meta-only profiles. No requirement to open-source internal packs.
