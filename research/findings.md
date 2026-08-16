# Analysis Package: consolidated research findings

**Date:** 2026-08-16  
**Status:** Research synthesis (Hermes parallel scan + standards pass)  
**Related:** `ANALYSIS-PACKAGE-STANDARD.md` (draft v0 semantics), `templates/analysis-package-manifest.example.yaml`

---

## 1. Question

Is there already a product or open standard for packaging **weekly planning/ops analyses** as portable, auditable, trainable artifacts (inputs + method + engines + human overrides/truths + QA)?

If not, which **existing standards** should we compose to define ours?

---

## 2. Executive answer

| Claim | Verdict |
|-------|---------|
| Something identical already dominates the market | **No** |
| Reusable packaging / lineage / dataset-card pieces exist | **Yes - many** |
| Greenfield opportunity | **Semantics + planner UX**, not "invent folders" |
| Recommended path | **Compose standards** into an **Analysis Package Profile**; invent only decision-label vocabulary |

**One-liner:**  
Nobody standardizes the *weekly planning decision pack* (Excel/Python reality) as label-grade portable token capital. You should **profile** RO-Crate + PROV + Table Schema + Web Annotation - not start from a blank JSON cult.

---

## 3. Product / platform landscape (fit 0-5)

| Name | Fit | Role vs us |
|------|----:|------------|
| [Quilt](https://www.quilt.bio/) | 4 | Closest *product*: versioned data+metadata packages, AI-ready pitch. Misses override/truth label model and planner workflow. |
| [RO-Crate](https://www.researchobject.org/ro-crate/) | 3.5 | Best *open package* substrate; profiles exist (Workflow RO-Crate, Workflow Run Crate). |
| [Frictionless Data Package](https://frictionlessdata.io/) | 3 | Lightweight `datapackage.json` + Table Schema; great for tabular I/O, thin on decisions. |
| [OpenLineage](https://openlineage.io/) | 3 | Job/run/dataset lineage events - emit from engines, not the human pack. |
| [Croissant](https://mlcommons.org/working-groups/data/croissant/) (MLCommons) | 3 | ML-ready dataset metadata; discovery/load, not weekly ops judgments. |
| DVC / MLflow / W&B | 2-3 | DS/ML experiment & data versioning - wrong unit of work (experiments ≠ S&OE packs). |
| Dagster asset checks etc. | 2.5 | Pipeline QA - engineering platform, not analyst package. |
| DataHub / OpenMetadata / Collibra | 2 | Catalogs - org graph, not a weekly artifact. |
| Scale / Labelbox / Snorkel | 2 | Labeling ops inspiration (guidelines, consensus, gold) - not planning packs. |
| Kinaxis / Anaplan / SAP IBP | 2 | Decisions stay **inside** the suite; not a portable open package. |

### Supply-chain specific
No strong portable open standard found for “planning analysis package with overrides-as-labels.” Suites optimize lock-in; your wedge is **beside** export/Excel reality.

---

## 4. Standards to build on (foundation stack)

### Recommended composition

```
Analysis Package Profile
├── RO-Crate 1.x          → package boundary, entities, people, files
│   └── optional Workflow / Workflow Run profile if code is a CWL/Nextflow-style workflow
├── W3C PROV-O            → wasGeneratedBy, used, associatedWith (who/what/when)
├── Frictionless Table Schema / JSON Schema → output & input table contracts
├── W3C Web Annotation    → overrides/judgments as annotations on fields/rows
├── Datasheet sections    → intended_use, out_of_scope, motivation (doc layer)
├── OpenLineage (optional emit) → when packs are produced by orchestrated jobs
└── OUR vocabulary        → reason_code, four_buckets, output_contract,
                            guideline_version, training_eligibility, gold_reference
```

### Why each layer

| Standard | Spec | Foundation job | Maps to our MUST |
|----------|------|----------------|------------------|
| **RO-Crate** | [researchobject.org/ro-crate](https://www.researchobject.org/ro-crate/) | Folder + `ro-crate-metadata.json` (JSON-LD); **profiles** for domain constraints | package id, files, authors, license, parts |
| **Workflow RO-Crate / Run Crate** | [Workflow RO-Crate](https://about.workflowhub.eu/Workflow-RO-Crate/), [workflow-run-crate](https://www.researchobject.org/workflow-run-crate/) | Package executable method + run provenance | method entrypoint, run as_of, inputs/outputs of execution |
| **W3C PROV** | [PROV-DM/PROV-O](https://www.w3.org/TR/prov-dm/) | Provenance graph semantics | analyst, inputs used, generation time |
| **Frictionless / Table Schema** | [specs.frictionlessdata.io](https://specs.frictionlessdata.io/) | Tabular resource descriptors + validation | output schemas, input tables |
| **W3C Web Annotation** | [annotation-model](https://www.w3.org/TR/annotation-model/) | Body/target annotations on specific segments | overrides (target=field/row), judgments |
| **Datasheets for Datasets** | [arXiv:1803.09010](https://arxiv.org/abs/1803.09010) | Human documentation checklist | purpose, intended use, maintenance |
| **Croissant** | [MLCommons Croissant](https://mlcommons.org/working-groups/data/croissant/) | Optional ML export profile when pack becomes training set | training_eligibility bridge |
| **OpenLineage** | [openlineage.io](https://openlineage.io/) | Optional runtime lineage bus | engine runs in platforms |
| **BagIt / OCFL** | integrity layouts | Optional bit-level checksum inventory | tamper-evidence |

### Fit as foundation (not full product)

| Standard | Score (0-5) | Notes |
|----------|------------:|-------|
| RO-Crate + profiles | 5 | Best extension story (`Analysis-Package-Profile`) |
| PROV-O | 4 | Provenance backbone |
| Web Annotation | 4 | Clean model for overrides-as-labels |
| Table Schema / JSON Schema | 4 | I/O contracts |
| Frictionless Data Package | 3.5 | Simpler alternative package root if RO-Crate feels heavy |
| Datasheets | 3 | Process/docs, not runtime |
| Croissant | 3 | Downstream ML handoff only |
| OpenLineage | 3 | Side channel for pipelines |
| GS1 / OAGIS / ISA-95 | 1-2 | Domain messages, not analysis packs |

---

## 5. What we still invent (the wedge)

Standards will not give you:

1. **`output_contract`** - inversion-native “who consumes this pack”  
2. **`reason_code` taxonomy** for planning overrides  
3. **Four buckets** (structured / judgment / truths / hard compute)  
4. **`guideline_version`** linked to living method cards for planners  
5. **`training_eligibility` + confidentiality** policy defaults for ops data  
6. **Gold pack regression** (“new script within tolerance of gold”)  
7. **Excel/Sheets-first authoring UX** with export to package  

That bundle is the product/standard delta.

---

## 6. Recommended approach (decision)

### Do this
1. **Define `analysis-package` as an RO-Crate profile** (or Frictionless profile if we prioritize simplicity over JSON-LD ecosystem).  
2. **Represent overrides** as Web Annotation bodies (or a thin JSONL profile that round-trips to Web Annotation).  
3. **Attach PROV** activities for “planning run” and agents (people + software).  
4. **Validate tables** with Table Schema / JSON Schema.  
5. **Write human datasheet sections** into `GUIDELINE.md` + manifest fields.  
6. **Optionally emit OpenLineage** when run under Dagster/Airflow.  
7. **Optionally export Croissant** when a pack is promoted to ML training.

### Do not do this
- Greenfield-only YAML with zero mapping to existing specs (hurts adoption and interop).  
- Compete with Kinaxis/Anaplan as system of record.  
- Assume Croissant alone is enough (no decision/override model).  
- Boil the ocean with full enterprise catalog (DataHub) before one pack type works.

### Phased delivery
| Phase | Deliverable |
|-------|-------------|
| P0 | Semantics freeze (our MUST fields) - mostly done in `ANALYSIS-PACKAGE-STANDARD.md` |
| P1 | RO-Crate profile draft + example crate from one real pack (e.g. commit pack) |
| P2 | Override JSONL ↔ Web Annotation mapping + reason_code v0 |
| P3 | Validator CLI + gold diff |
| P4 | Blog essay + optional thin product (packager) |

---

## 7. Greenfield claim (blog/investor safe wording)

> We are not inventing data versioning. We are defining the missing **unit of work** for enterprise judgment: a portable **analysis package** that treats planner overrides and truths like labels, with input snapshots and method versions, so ops token capital can compound outside any single suite.

---

## 8. Decisions

### Already locked (do not re-litigate unless you reopen)

| # | Decision | Choice |
|---|----------|--------|
| L1 | Purpose | Formal **agent–human planner contract**, not optional research packaging |
| L2 | Properties | Portable, deterministic core, extensible, process-universal fit |
| L3 | Architecture | **Compose standards**; invent thin domain vocab only |
| L4 | Greenfield claim | Intersection is open (planner pack as labels+snapshots+guideline+QA); pieces exist |
| L5 | Suites (Kinaxis/IBP/etc.) | Emitters / systems of record - **not** the portable standard |
| L6 | Research phase | **Enough** - next is design validation + build, not more landscape scans |
| L7 | Normative doc | `ANALYSIS-PACKAGE-STANDARD.md` **ap/0.2** |

### Open decisions (need captain)

Each row: options, tradeoff, **Hermes recommendation**.

#### D1 - Root envelope format

| Option | Pros | Cons |
|--------|------|------|
| **A. RO-Crate profile** | First-class profiles, PROV-native, Workflow Run ecosystem, long-term interop | JSON-LD learning curve; “research” brand |
| **B. Frictionless Data Package** | Simple JSON, Table Schema native, fast for tabular packs | Weaker provenance/annotation story; bolt on PROV/labels yourself |
| **C. Hybrid** | Frictionless for v0 authoring; map to RO-Crate for publish | Two serializers to maintain |

**Recommend: A (RO-Crate profile)** for the formal contract story, with a **YAML convenience manifest** that compiles to `ro-crate-metadata.json` so agents/planners never hand-write JSON-LD.

#### D2 - First pack-type profile (vertical)

| Option | Why pick it |
|--------|-------------|
| **A. Supplier / commodity commit–forecast pack** | You have lived vignette + six-file pattern; strongest proof |
| **B. Exception / aging pack** | Smaller; faster pilot |
| **C. FP&A flash** | Tests universality beyond SC; less personal source material now |

**Recommend: A** - prove the contract on the process you know; add B as second profile to stress “universal fit.”

#### D3 - Public vs internal standard

| Option | Pros | Cons |
|--------|------|------|
| **A. Internal only until 1–2 real packs** | Faster iteration; no premature API promises | Weaker external credibility |
| **B. Public GitHub profile (TM-Elden) early** | Forces clarity; blog/investor story | Change management / issues |
| **C. Public blog essay now, schema repo later** | Narrative without freezing bits | Split brain |

**Recommend: C then A→B** - essay can cite the model; freeze profile in public repo after one real pack validates MUST fields.

#### D4 - Label serialization

| Option | Pros | Cons |
|--------|------|------|
| **A. Web Annotation JSON-LD jsonl** | Standard selectors/bodies; interop | Heavier |
| **B. Thin ap override jsonl** (current draft) + optional WA export | Easy for agents/Excel export | Custom until mapped |
| **C. Both** (B canonical authoring, A export) | Best of both | Mapping tests |

**Recommend: C** - agents write simple jsonl; validator can emit Web Annotation view.

#### D5 - Determinism policy for model-assisted steps

| Option | Meaning |
|--------|---------|
| **A. Strict** | Models may draft only; accepted outputs must be engine- or human-label-backed |
| **B. Declared non-deterministic engines** allowed with flag + extra QA |
| **C. Allow model as engine if temperature 0 and pinned prompt hash** | Soft determinism |

**Recommend: A as default for ap/0.2** (matches “chat is not MRP”); allow B only behind pack-type opt-in.

#### D6 - Completeness gate enforcement

| Option | Where gate runs |
|--------|-----------------|
| **A. Agent-side only** (refuse “final” in harness) | Fast; depends on every harness |
| **B. CI/validator CLI on package dir** | Portable; harness-agnostic |
| **C. Both** | Defense in depth |

**Recommend: C** - CLI is source of truth; agents call same checks.

#### D7 - Training eligibility default

| Option | Default |
|--------|---------|
| **A. opt-in** (`training_eligibility: false` unless set) | Safer for enterprise |
| **B. opt-out** | More token capital by default; riskier |

**Recommend: A**

#### D8 - Next build milestone

| Option | Deliverable |
|--------|-------------|
| **A. Profile stub + JSON Schema + empty crate** | Spec skeleton |
| **B. One real filled package from your process** | Validation |
| **C. A+B together** | Best learning |

**Recommend: C** - stub without a real pack will lie; pack without schema won’t gate agents.

---

### Decision log template (fill when you choose)

```text
D1 root:     A / B / C
D2 pack type: A / B / C
D3 publicity: A / B / C
D4 labels:   A / B / C
D5 model:    A / B / C
D6 gate:     A / B / C
D7 train:    A / B
D8 build:    A / B / C
date:
```

Reply with a line like `D1A D2A D3C D4C D5A D6C D7A D8C` to freeze and start build.

---

## 9. Primary links (bookmark set)

**Packaging & workflows**
- https://www.researchobject.org/ro-crate/
- https://www.researchobject.org/ro-crate/profiles
- https://about.workflowhub.eu/Workflow-RO-Crate/
- https://www.researchobject.org/workflow-run-crate/
- https://frictionlessdata.io/
- https://specs.frictionlessdata.io/

**Provenance & annotation**
- https://www.w3.org/TR/prov-dm/
- https://www.w3.org/TR/annotation-model/
- https://openlineage.io/

**ML dataset metadata**
- https://mlcommons.org/working-groups/data/croissant/
- https://arxiv.org/abs/1803.09010 (Datasheets for Datasets)
- https://huggingface.co/docs/hub/en/datasets-cards

**Closest product analog**
- https://www.quilt.bio/
- https://github.com/quiltdata/quilt

**Our drafts**
- `meta/ANALYSIS-PACKAGE-STANDARD.md`
- `meta/templates/analysis-package-manifest.example.yaml`
- `meta/research/2026-08-16-analysis-package-landscape.md` (earlier product scan)

---

## 10. Research process note

Two background research agents completed:

| Agent | Deliverable |
|-------|-------------|
| Landscape `deleg_452a2655` | `meta/research/2026-08-16-analysis-package-landscape-full.md` |
| Standards foundation `deleg_03159111` | `meta/research/2026-08-16-analysis-package-standards-foundation.md` |

Both agree with this synthesis: **compose RO-Crate profile + PROV + Table/JSON Schema + Web Annotation + optional OpenLineage**; invent thin `ap:` vocab only. Hosted HTML is the captain summary; full agent catalogs are markdown on the same static path.
