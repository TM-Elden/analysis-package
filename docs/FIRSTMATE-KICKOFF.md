# fathm kickoff (firstmate / captain)

**Date:** 2026-08-16  
**Build authority:** `docs/DESIGN-FATHM-SYSTEM.md`  
**Repo:** https://github.com/TM-Elden/analysis-package  

## Scope
Full fathm system is in scope:

**Core:** standard, gate/CI, store, manager bot, company bot, planner bot, Standard HITL, agent contract, trust  

**Also required for complete:** package review, authz, lifecycle (supersede/recall/retention), standard migration, PII redaction for index, eval harness, webhooks, cycle diff, gold packs, operator surface  

**Backlog (not required for complete bar):** connectors, billing, multi-env, airgap, public docs/SDKs, collab comments, LLM cost caps, i18n  

See capability tables C1-C19 and B1-B8 in DESIGN-FATHM-SYSTEM.md.

## Phasing
**You decide.** Hermes does not prescribe sprint order or v0 cuts.  
Complete product = acceptance list in DESIGN-FATHM-SYSTEM.md §18.

## Brand
- Product: **fathm** (always lowercase wordmark; sunk brass "a")
- Format: **Analysis Package (ap)**
- Visual system: `brand/fathm-brand-system-v1.html`
- Metaphor: **chart room**
- CLI/library preference: `ap-gate` for validation

## Start
```bash
cd ~/firstmate/projects/analysis-package && git pull
# read docs/DESIGN-FATHM-SYSTEM.md and build
```
