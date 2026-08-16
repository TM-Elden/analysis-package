# Analysis Package

**Working product name:** Analysis Package (AP)  
**Tagline:** The publish contract for AI-assisted planning and finance analysis.

Every package carries pinned data, method, human overrides, and a CI gate - so provenance is queryable by default, not reconstructed in an audit.

This repo is the **joint home** for:

1. **The Standard** (`standard/`) - formal interchange contract for human planners + planning agents  
2. **The Product** (`product/`, `docs/PITCH.md`) - Standard + L1 CI wedge, then Team Model / Planner Model  
3. **Research** (`research/`) - landscape, standards foundation, source pitch  

Status: **early draft**. Pilot scope is Standard + L1 structural CI for one pack type - not the full platform.

---

## Why

Analysis conclusions often cannot be traced to the data and method that produced them. As AI agents draft more planning and finance analysis, that liability compounds. Spreadsheets and chat are not an audit trail.

**Analysis Package** is the portable unit of work: inputs, method, engines, labeled human deltas, outputs, QA.

---

## Repo map

```
standard/ap-0.2/          Normative Standard (ap/0.2)
profiles/                 Pack-type profiles (first: commodity commit forecast)
examples/                 Concrete packages
product/                  Product layers (CI L1/L2, trust, roadmap)
docs/                     Pitch, architecture, decisions, HTML guides
research/                 Prior art and source materials
```

| Doc | Purpose |
|-----|---------|
| [standard/ap-0.2/STANDARD.md](standard/ap-0.2/STANDARD.md) | Normative contract |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Product + Standard join; L1/L2 CI |
| [docs/PITCH.md](docs/PITCH.md) | Pitch v3 (updated) |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Frozen D1-D8 |
| [docs/html/spec-guide.html](docs/html/spec-guide.html) | Polished HTML spec guide |
| [examples/commodity-commit-v1/](examples/commodity-commit-v1/) | Example package |

---

## Design goals

| Goal | Meaning |
|------|---------|
| **Portable** | Self-contained directory; no chat session as source of truth |
| **Deterministic core** | Pinned inputs + versioned engines + labeled overrides |
| **Extensible** | MUST core stable; pack-type profiles for domain shape |
| **Universal fit** | Process-shaped (any planner who can name I/O + method + overrides) |

**Envelope:** RO-Crate profile (YAML convenience manifest for authoring).  
**Labels:** thin jsonl authoring; optional Web Annotation export.  
**Models:** draft only by default - not silent planning math.

---

## Product layers (sequenced)

```
L1  Standard + structural CI gate     ← pilot (90 days)
L2  Semantic CI (LLM-assisted flags)  ← after L1 proves
L3  Team Model (per-customer RAG)     ← after publish corpus exists
L4  Planner Model + HITL on Standard  ← corpus moat tier
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Quick start (example pack)

```bash
cd examples/commodity-commit-v1
cat MANIFEST.yaml
cat labels/overrides.jsonl
python code/run_commit_pack.py   # stub entrypoint today
```

Validator CLI (`ap-gate`) is not shipped yet - see roadmap.

---

## Trust stance (decided)

- Train **only** on structure and conformance behavior (how packages fail/fix gates)  
- **Never** train on underlying business content for cross-customer models  
- **Never** pool one customer's content into a model resold to another  
- Per-customer Team Models stay isolated  

---

## Roadmap (near)

- [ ] JSON Schema for MANIFEST MUST fields  
- [ ] `ap-gate` CLI (L1 structural)  
- [ ] YAML → RO-Crate compiler  
- [ ] One real (redacted) design-partner pack  
- [ ] Second pack type (prove universal fit)  

---

## License

MIT (see [LICENSE](LICENSE)).

## Author

Tom Moore ([TM-Elden](https://github.com/TM-Elden))
