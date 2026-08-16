# fathm kickoff (firstmate / captain)

**Date:** 2026-08-16  
**Build authority:** `docs/DESIGN-FATHM-SYSTEM.md`  
**Repo:** https://github.com/TM-Elden/analysis-package  

## Scope
Full fathm system is in scope:

- Analysis Package **standard**
- **Gate / CI** (structural + semantic capability)
- **Package store**
- **Manager bot** (team RAG)
- **Company bot** (org RAG)
- **Planner bot** (Standard/profile proposals)
- **HITL approval** (mandatory before Standard goes live)
- **Agent runtime contract** + trust/tenancy

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
