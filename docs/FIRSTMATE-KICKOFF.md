# fathm MVP kickoff (firstmate / captain)

**Date:** 2026-08-16  
**Design:** `docs/DESIGN-FATHM-MVP.md` in https://github.com/TM-Elden/analysis-package  

## Build
Implement **ap-gate** L1 structural validator only.

## Brand
- Product: **fathm** (understand fully, down to its source)
- Format: **Analysis Package** (`ap/0.2`)
- CLI name: `ap-gate`

## Done when
1. `ap-gate check examples/commodity-commit-v1` exits 0  
2. Negative fixtures fail correctly  
3. `--json` and `--html` work  
4. GH Actions CI green on PR  
5. README install/usage updated  

## Do not build
Team Model, Planner Model, L2 LLM judge, SaaS, RO-Crate compiler, Excel add-in.

## Branch
`feat/ap-gate-l1` → PR to `main`

## Clone
```bash
cd ~/firstmate/projects || mkdir -p ~/firstmate/projects && cd ~/firstmate/projects
git clone https://github.com/TM-Elden/analysis-package.git
cd analysis-package
git pull
# read docs/DESIGN-FATHM-MVP.md and execute
```
