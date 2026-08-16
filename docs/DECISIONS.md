# Decision log - Analysis Package Standard

Frozen: 2026-08-16  
Source: captain agreed to all Hermes recommendations on findings-v2.

| ID | Topic | Choice | Meaning |
|----|--------|--------|---------|
| D1 | Root envelope | **A** | RO-Crate profile; YAML convenience manifest compiles to `ro-crate-metadata.json` |
| D2 | First pack type | **A** | Supplier / commodity commit–forecast pack |
| D3 | Publicity | **C** | Blog/essay narrative OK now; public schema repo after 1+ real packs |
| D4 | Labels | **C** | Thin `ap` jsonl authoring; optional Web Annotation export |
| D5 | Model policy | **A** | Strict: models draft only; accepted math is engine- or human-label-backed |
| D6 | Gate | **C** | Validator CLI is source of truth; agents must call same checks |
| D7 | Training default | **A** | `training_eligibility` opt-in (default false) |
| D8 | Build | **C** | Profile/schema stub + example real-shaped pack |

Locked earlier: L1–L7 in findings (formal agent–planner contract, compose standards, ap/0.2).
