# Decision log - fathm / Analysis Package

Frozen product brand: **fathm** (2026-08-16).  
Format/standard name remains **Analysis Package (ap)**.

| ID | Topic | Choice | Meaning |
|----|--------|--------|---------|
| D0 | Product brand | **fathm** | v. understand fully, down to its source; AP stays the format |
| D1 | Root envelope | **A** | RO-Crate profile; YAML convenience manifest compiles to `ro-crate-metadata.json` |
| D2 | First pack type | **A** | Supplier / commodity commit–forecast pack |
| D3 | Publicity | **C** | Blog/essay narrative OK now; public schema repo after 1+ real packs |
| D4 | Labels | **C** | Thin `ap` jsonl authoring; optional Web Annotation export |
| D5 | Model policy | **A** | Strict: models draft only; accepted math is engine- or human-label-backed |
| D6 | Gate | **C** | Validator CLI is source of truth; agents must call same checks |
| D7 | Training default | **A** | `training_eligibility` opt-in (default false) |
| D8 | Build | **C** | Profile/schema stub + example real-shaped pack |

Also locked: L1–L7 formal agent–planner contract, compose standards, ap/0.2.  
Brand detail: `brand/BRAND.md` / `docs/BRAND.md`.  
Vision: `docs/VISION.md` (in-agent enforcement; standard purposes: lineage, reproducibility, portability, governance, credit, opt-in training corpus, later Q&A).

| D0b | Brand visual | **final** | F-as-sounding-line lockup; see `brand/fathm-brand-final.html` |
| D9 | Standard purposes | **multi** | Lineage, reproducibility, portability, governance/credit, interoperability, opt-in training/eval - enforced via one package shape in-agent |
| D10 | Product locus | **in-agent** | Primary product is agent-side standard+gate; platform consumers optional later |
