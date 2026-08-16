# Analysis Package Standard — Foundation Stack Research

**Date:** 2026-08-16  
**Scope:** Open data standards, packaging specs, provenance models, and metadata frameworks that can be *adopted or profiled* (not product landscape).  
**Goal:** Compose-from-standards foundation for an Analysis Package (planning/ops/FP&A decision packs: identity, inputs, method, overrides-as-labels, QA, intended use).

---

## A. Top 5 recommended foundation stack

**Primary recommendation (compose, do not greenfield):**

| Layer | Standard | Role in Analysis Package |
|-------|----------|---------------------------|
| **1. Package envelope** | **RO-Crate 1.2/1.3 profile** (`Analysis Package Profile`) | On-disk crate + `ro-crate-metadata.json` JSON-LD; identity, parties, parts, purpose, conformsTo |
| **2. Provenance** | **W3C PROV-O / PROV-DM** (embedded in RO-Crate provenance section + optional PROV-JSONLD bundle) | Entity/Activity/Agent: analyst, reviewer, run, as_of, derivation of outputs from inputs |
| **3. Tabular/schema** | **Frictionless Table Schema (+ Data Resource)** and/or **JSON Schema** | `outputs/` + `inputs/` schemas; output_contract as schema refs |
| **4. Labels / overrides** | **W3C Web Annotation Data Model** (JSON-LD; jsonl of Annotation objects) | Overrides, judgments, planner truths targeting cells/files/sections |
| **5. Run/lineage facet (ops bridge)** | **OpenLineage** Job/Run/Dataset facets (as *exportable* companion events, not sole store) | Engine runs, snapshot_id, source_system, deterministic flag via custom facets |

**Supporting / optional layers:**

| Layer | Standard | When |
|-------|----------|------|
| Integrity wrap | **BagIt (RFC 8493)** | Ship/transfer; checksum manifests; RO-Crate documents BagIt combination |
| Archive store | **OCFL 1.0** | Long-term versioned object store of packages (not the package schema itself) |
| Workflow method | **Workflow RO-Crate + Workflow Run Crate** profiles; optional **CWL** for entrypoint | Versioned guideline + executable method + run provenance |
| Catalog discoverability | **schema.org Dataset + DCAT 3** (subset in crate root) | Portal/search; intended_use / license hooks |
| Training / RAI surface | **Croissant** (+ RAI extension) as *export view* | training_eligibility, feature/record semantics for ML reuse—not primary ops package |
| Doc template cousins | Datasheets for Datasets / Model Cards | Narrative sections for purpose, out_of_scope, QA—not machine envelope |
| Financial reporting cousin | **XBRL Report Packages** | Only if packing regulatory financial *reports*; weak for analytical decision runs |

**One-line stack slogan:**  
> **RO-Crate Analysis-Package Profile + PROV + Table Schema/JSON Schema + Web Annotation (labels/) + OpenLineage facets (runtime bridge), optionally BagIt-wrapped.**

---

## B. Comparison table (promising standards)

Fit score = foundation-layer fitness for *our* Analysis Package (0–5).

| Standard | Body / primary URL | Serializes | Extension/profile? | Fit | Clean MUST maps | Needs custom vocab | Risks |
|----------|-------------------|------------|--------------------|-----|-----------------|--------------------|-------|
| **RO-Crate** | researchobject.org; [spec 1.2](https://w3id.org/ro/crate/1.2), [profiles](https://www.researchobject.org/ro-crate/specification/1.2/profiles.html) | JSON-LD (`ro-crate-metadata.json`); dir layout | **First-class profiles** (`conformsTo`, Profile Crate, dx-prof roles) | **5** | identity, version, parts (inputs/code/outputs), author/creator, license, hasPart layout, workflows | as_of, output_contract, training_eligibility, four-bucket map, QA status enums | Research-heavy brand; JSON-LD learning curve; enterprise ops unfamiliarity |
| **Workflow RO-Crate / Workflow Run Crate** | [WorkflowHub WROC](https://about.workflowhub.eu/Workflow-RO-Crate/); [WRROC](https://www.researchobject.org/workflow-run-crate/); w3id.org/ro/wfrun | RO-Crate JSON-LD + CreateAction | Profiles extending RO-Crate | **4** | method entrypoint, engines, run provenance, inputs/outputs of a run | FP&A overrides, business QA gold, confidentiality labels | Bio/workflow ecosystem bias; may overfit to workflow engines |
| **Frictionless Data Package v1/v2** | [specs.frictionlessdata.io](https://specs.frictionlessdata.io/data-package/); [datapackage.org](https://datapackage.org/) | JSON `datapackage.json` | **profile** / `$schema` profiles; extensions | **4** | package name/id/version, resources, contributors, sources, licenses; Table Schema | rich provenance, annotations, method as first-class, QA gold | Weaker linked-data provenance; dual v1/v2 during transition; less “research object” for code+labels+QA |
| **BagIt** | IETF [RFC 8493](https://datatracker.ietf.org/doc/html/rfc8493) | bagit.txt, manifests, bag-info.txt, data/ | bag-info metadata; no deep semantic profile | **3** | integrity, transfer packaging | almost all semantic MUST fields | Complements envelope; not a semantic foundation alone |
| **OCFL** | [ocfl.io/1.0/spec](https://ocfl.io/1.0/spec/) | inventory.json + versioned dirs | Extensions registry | **2** | versioned storage of packages | package semantics | Storage layout for repositories, not analysis semantics |
| **OAI-ORE** | [openarchives.org/ore](https://www.openarchives.org/ore/) | Atom/RDF Resource Maps | Aggregation model | **2** | conceptual aggregation | everything practical | Ancestor of RO; superseded in practice by RO-Crate for file crates |
| **W3C PROV-DM / PROV-O** | [PROV-DM](https://www.w3.org/TR/prov-dm/); [PROV-O](https://www.w3.org/TR/prov-o/); [PROV-JSON](https://www.w3.org/Submission/prov-json/); [PROV-JSONLD](https://www.w3.org/submissions/2024/SUBM-prov-jsonld-20240825/) | PROV-N, RDF/OWL, XML, JSON, JSON-LD | Subclassing + attributes; bundles | **5** | analyst/reviewer (Agent), run (Activity), inputs/outputs (Entity), wasGeneratedBy, used, as_of times | domain labels for “planner truth”, QA check types | Abstract; needs concrete serialization choice; easy to over-model |
| **OpenLineage** | [openlineage.io](https://openlineage.io/docs/spec/facets/); [OpenLineage.json](https://github.com/OpenLineage/OpenLineage/blob/main/spec/OpenLineage.json) | JSON events + JSON Schema facets | **Custom facets** (`prefix_name`, `_schemaURL`) | **4** | job/run/dataset, schema facet, datasource, version/snapshot facets, ownership | full package layout, labels, intended_use, training | Event-stream oriented (not archival package); facet sprawl; LF AI governance |
| **Croissant** | MLCommons; [spec 1.0](https://docs.mlcommons.org/croissant/docs/croissant-spec-1.0.html); [mlcommons.org/croissant](https://mlcommons.org/croissant/) | JSON-LD on schema.org Dataset | RAI extension; community extensions; `conformsTo` | **3** | dataset identity, files, recordSets, license, some RAI/usage | ops decision package, method engines, override labels as first-class | ML-dataset-centric; not designed for weekly decision packs |
| **schema.org Dataset** | [schema.org/Dataset](https://schema.org/Dataset) | JSON-LD / Microdata | external vocabs in JSON-LD | **3** | name, description, creator, license, temporalCoverage, distribution | method, QA, labels | Too shallow alone; good as RO-Crate base types |
| **DCAT / DCAT-AP** | W3C [DCAT 3](https://www.w3.org/TR/vocab-dcat-3/); EU DCAT-AP | RDF | Application profiles | **3** | catalog Dataset/Distribution, publisher, themes | run method, labels, QA gold | Catalog interchange, not self-contained analysis runs |
| **DATS / Bioschemas** | DATS; [bioschemas.org](https://bioschemas.org/) | JSON-LD | profiles | **2** | dataset annotation patterns | non-bio domains | Domain-skewed |
| **Table Schema** | Frictionless [table-schema](https://specs.frictionlessdata.io/table-schema/) | JSON | open properties + profile | **5** | output/input tabular schemas, constraints, PK/FK | nested financial structures (use JSON Schema) | CSV-first mental model |
| **JSON Schema** | [json-schema.org](https://json-schema.org/) | JSON | `$id`, vocabularies, dialects | **5** | output_contract, non-tabular outputs | — | Ubiquitous; pair with Table Schema for CSV |
| **Apache Avro / Parquet schema** | Apache | Avro JSON / Parquet footer | schema evolution | **3** | physical engine schemas | package metadata | Physical, not package standard |
| **CWL** | [commonwl.org v1.2](https://www.commonwl.org/v1.2/) | YAML/JSON (SALAD) | requirements, hints | **3** | versioned method entrypoint, containers, deterministic-ish runs | business guideline narrative | Ops teams may not use CWL; optional for method/ |
| **Whole Tale / ReproZip** | [reprozip.org](https://www.reprozip.org/); Whole Tale project | tool-specific packages | — | **2** | env capture inspiration | standard interchange | Tools more than interchange standards |
| **Web Annotation DM** | W3C [annotation-model](https://www.w3.org/TR/annotation-model/) | JSON-LD (`application/ld+json;profile=...anno.jsonld`) | motivations, bodies, selectors | **5** | overrides/judgments targeting resources/fragments; agents; lifecycle | “planner truth” motivation terms, confidence, supersedes | Selector complexity; train analysts on body/target pattern |
| **ADR (MADR etc.)** | Community templates | Markdown | — | **1** | decision narrative cousin | structured package | Weak as machine standard; optional human notes |
| **XBRL / Report Packages** | [xbrl.org](https://www.xbrl.org/); Report Packages rec | XML/JSON/CSV + zip package layout | taxonomies | **2** | financial fact contexts, periods | analytical overrides, method code, training | Regulatory reporting, not ops analysis runs; heavy |
| **GS1 / ISA-95 / OAGIS / UN/CEFACT** | GS1, ISA, OAGi, UNECE | EDI/XML/JSON variously | messages / BIE | **1–2** | thin: plan/order/forecast message types | entire Analysis Package concept | Transaction/master-data messages; no analysis-run package |
| **ISO 8000** | ISO 8000 series (data quality) | mostly process requirements | — | **2** | QA *concepts* (quality characteristics, maturity) | concrete check schema | Management standard, not package format |
| **Datasheets / Nutrition Labels / Model Cards** | Gebru et al.; Data Nutrition Project; Mitchell et al. | Markdown/PDF/HTML templates | — | **2** | purpose, out_of_scope, intended_use, confidentiality narrative | machine validation | Documentation practices; encode fields in profile JSON-LD |

---

## C. Concrete proposal: base format + extension points + what we invent

### C.1 Base format

**On-disk layout (align to RO-Crate + your MUST dirs):**

```text
analysis-package-<id>/
  ro-crate-metadata.json          # MANIFEST equivalent (JSON-LD)
  ro-crate-preview.html           # optional human view
  GUIDELINE.md | guideline/       # versioned method narrative (+ link from crate)
  inputs/                         # snapshots or refs
  code/                           # entrypoints, transforms
  outputs/                        # products + schema sidecars
  labels/                         # *.jsonl Web Annotations
  qa/                             # checks, status, optional gold/
  # optional:
  provenance/                     # PROV-JSONLD bundle if not all in-crate
  openlineage/                    # run events export
  bagit.txt + manifest-sha256.txt # if BagIt-wrapped for transfer
```

**Root entity:** `@type: Dataset` (RO-Crate Root Data Entity) with:

- `conformsTo`: `https://w3id.org/.../analysis-package/0.1` **and** `https://w3id.org/ro/crate/1.2`
- optionally also Workflow Run profile if method is a workflow run

### C.2 Analysis Package Profile (what we *profile*, not invent from zero)

Publish as RO-Crate **Profile Crate** (dx-prof ResourceDescriptors for human spec, JSON Schema/SHACL constraints, examples).

| MUST concern | Map to existing | Profile rule / light invent |
|--------------|-----------------|------------------------------|
| package identity + version + as_of | `identifier`, `version`, `datePublished` / `temporalCoverage`; PROV `generatedAtTime` | **Invent:** `ap:asOf` (xsd:dateTime) on root + each input Entity |
| analyst + reviewer | schema.org `author`/`creator`; PROV `wasAttributedTo` / `wasAssociatedWith` with roles | **Profile:** require two Agents with `ap:role` ∈ {analyst, reviewer} |
| purpose + output_contract | `description`, `about`; JSON Schema / Table Schema as File entities | **Invent:** `ap:outputContract` → schema `@id`s; `ap:purpose` text or DefinedTerm |
| inputs: snapshot_id, source_system, as_of | Data entities + PROV; OpenLineage Dataset `version` / datasource facets | **Invent:** `ap:snapshotId`, `ap:sourceSystem` on input File/Dataset |
| method: guideline + entrypoint/repro | RO-Crate ComputationalWorkflow / File `programmingLanguage`; `CreateAction`; CWL optional | **Profile:** require `ap:guideline` File + `ap:entrypoint` (URI or File) |
| engines + deterministic flag | SoftwareApplication; WRROC; OL Run facets | **Invent:** `ap:engine`, `ap:deterministic` (boolean) |
| outputs + schemas | hasPart File + `conformsTo` schema; Table Schema / JSON Schema | Profile only |
| labels: overrides, judgments, planner truths | **Web Annotation** in `labels/*.jsonl` | **Invent:** motivation terms `ap:override`, `ap:judgment`, `ap:plannerTruth` (+ body payload schema) |
| QA status + checks + gold | File entities in `qa/`; could use CheckResult-like custom type | **Invent:** `ap:qaStatus`, `ap:Check`, `ap:goldReference` |
| intended_use, out_of_scope, confidentiality, training_eligibility | schema.org `conditionsOfAccess`, `license`, `usageInfo`; Croissant RAI-inspired | **Invent:** `ap:intendedUse`, `ap:outOfScope`, `ap:confidentiality`, `ap:trainingEligibility` |
| four-bucket context map | — | **Invent:** `ap:contextMap` object or 4 DefinedTerm sets (only if still required) |

Namespace suggestion: `https://w3id.org/<org>/ns/analysis-package#` (prefix `ap:`), declared in profile JSON-LD `@context` extension (RO-Crate supports context extension).

### C.3 Serialization choices (opinionated defaults)

1. **Canonical package metadata:** RO-Crate JSON-LD 1.2+.  
2. **Labels:** newline-delimited Web Annotation JSON-LD (jsonl) for stream-friendly ops.  
3. **Schemas:** Table Schema for CSV/Parquet columnar; JSON Schema for nested JSON outputs.  
4. **Provenance:** prefer in-crate PROV via RO-Crate provenance properties; optional `provenance/prov.jsonld` (PROV-JSONLD) for heavy graphs.  
5. **Runtime bridge:** emit OpenLineage COMPLETE events with custom `ap_*` facets pointing at package URI.  
6. **Transfer:** optional BagIt around the crate directory.  
7. **ML export (optional transform):** generate Croissant view when `trainingEligibility` allows.

### C.4 What we invent (minimize)

Only a **thin domain vocabulary + Profile document**, not a parallel packaging system:

- ~15–25 `ap:` terms (asOf, snapshotId, sourceSystem, outputContract, qaStatus, motivations, trainingEligibility, …)
- Profile MUST/SHOULD rules and directory conventions
- JSON Schemas for annotation bodies and QA check records
- One reference validator (profile crate + SHACL or JSON Schema)

**Do not invent:** new packaging envelope, new provenance graph model, new annotation model, new tabular schema language.

### C.5 Relationship to Frictionless-only alternative

A **Frictionless Data Package profile** alone scores well for data resources but forces custom JSON for PROV-class provenance, annotations, and workflow method. Prefer **RO-Crate as envelope** and *embed* Frictionless Table Schema / resources as described files (or dual-write `datapackage.json` for tooling that expects it).

---

## D. What NOT to base on (and why)

| Candidate | Why not as foundation |
|-----------|----------------------|
| **Greenfield single YAML/JSON schema** | Reimplements packaging, provenance, annotations poorly; zero interop; high long-term cost |
| **OAI-ORE alone** | Conceptual ancestor; insufficient modern tooling vs RO-Crate |
| **OCFL as package schema** | Excellent *repository* layout; silent on analysis semantics |
| **BagIt alone** | Integrity + transfer only |
| **OpenLineage alone** | Run *events*, not archival multi-artifact decision pack with labels/QA/guideline |
| **Croissant alone** | ML dataset load/discover; missing ops method/override/QA package shape |
| **DCAT alone** | Catalog records, not runnable analysis bundles |
| **MLflow / DVC formats** | Product/tool formats (prior scan); not neutral open foundation |
| **ISA-95 / OAGIS / GS1 / UN/CEFACT as package core** | Supply-chain *transaction* and B2B messages; no analysis-run package, labels, or QA gold model—may reference external IDs only |
| **XBRL Report Packages as core** | Financial *regulatory reporting* facts/taxonomies; wrong granularity for weekly analytical decision packs (optional export of some outputs) |
| **ISO 8000 as format** | Process/quality management requirements; use to *inspire* QA dimensions, not serialize packages |
| **ADR markdown alone** | Human decision notes; not inputs/method/outputs/labels machine package |
| **ReproZip/Whole Tale as standard** | Valuable capture tools; not multi-vendor interchange standards for your domain |

---

## E. Three open questions for Captain

1. **Canonical identity & time:** Is `as_of` a single package-level business time (plus per-input as_of), and should package `version` be semver of *method/guideline* while each weekly run is a new immutable package `identifier` (run id)? This drives PROV Entity vs Activity modeling and OL runId strategy.

2. **Labels authority model:** Must overrides be **Web Annotations** with full target selectors (row/column/cell), or is a simpler **jsonl “patch” record** (path, old, new, reason, agent) enough—with Annotation as a normative *mapping* for interop? (Affects analyst UX vs standards purity.)

3. **Enterprise consumption path:** Primary consumers = (a) internal data platform + training lake, (b) workflow engines (CWL/Nextflow/Airflow), or (c) document/audit archive?  
   - (a) → prioritize Croissant export + OL facets  
   - (b) → prioritize Workflow Run Crate + CWL  
   - (c) → prioritize BagIt/OCFL + PROV completeness  
   Order of investment in dual-writes depends on this.

---

## Appendix: Per-standard digests (citation anchors)

### Packaging

**Research Object Crate (RO-Crate)**  
- Body: researchobject.org community  
- Spec: https://w3id.org/ro/crate/1.2 (1.3 listed current LTR on site)  
- Aggregates files + metadata in a directory with JSON-LD metadata; schema.org-based; first-class **profiles** via `conformsTo` and Profile Crates (W3C dx-prof roles).  
- Fit **5**. Combine with BagIt as noted in profile packaging guidance.

**Frictionless Data Package**  
- Spec: https://specs.frictionlessdata.io/data-package/ ; v2: https://datapackage.org/  
- JSON descriptor + resources; profiles/extensions; Table Schema sibling.  
- Fit **4** as schema/resource layer or dual envelope.

**BagIt** — RFC 8493 https://datatracker.ietf.org/doc/html/rfc8493 — Fit **3** (integrity wrap).

**OCFL** — https://ocfl.io/1.0/spec/ — Fit **2** (store).

**OAI-ORE** — https://www.openarchives.org/ore/ — Fit **2** (historical aggregation model).

### Provenance & lineage

**PROV-DM / PROV-O** — https://www.w3.org/TR/prov-dm/ , https://www.w3.org/TR/prov-o/  
Entity, Activity, Agent, derivation, bundles; extensibility points. Fit **5**.

**OpenLineage** — https://openlineage.io/docs/spec/facets/  
Job/Run/Dataset + versioned JSON Schema facets; custom facets with `_schemaURL`. Fit **4** as runtime bridge.

### ML / catalog metadata

**Croissant** — https://docs.mlcommons.org/croissant/docs/croissant-spec-1.0.html  
JSON-LD schema.org Dataset + FileObject/FileSet/RecordSet; RAI extension. Fit **3** export.

**DCAT 3** — https://www.w3.org/TR/vocab-dcat-3/ — Fit **3** catalog.

**schema.org Dataset** — https://schema.org/Dataset — Fit **3** base types (already in RO-Crate).

### Schemas

**Table Schema** — https://specs.frictionlessdata.io/table-schema/ — Fit **5**.  
**JSON Schema** — https://json-schema.org/ — Fit **5**.

### Workflow / repro

**CWL** — https://www.commonwl.org/v1.2/ — Fit **3** optional method.  
**Workflow RO-Crate / Workflow Run Crate** — https://about.workflowhub.eu/Workflow-RO-Crate/ , https://www.researchobject.org/workflow-run-crate/ , https://w3id.org/ro/wfrun — Fit **4**.

### Annotation / decision

**Web Annotation Data Model** — https://www.w3.org/TR/annotation-model/ — Fit **5** for labels/.  
ADR — documentation only — Fit **1**.  
**XBRL** — https://www.xbrl.org/ — Report Packages for regulatory reports — Fit **2** side channel.

### Audit / quality

**ISO 8000** — conceptual DQ framework — Fit **2** (inspire QA dimensions).  
No strong open “evidence package” standard superseding RO-Crate+PROV for this use case.

### Supply-chain message standards

GS1, ISA-95, OAGIS, UN/CEFACT: useful as **external identifiers / reference data** inside inputs, not as Analysis Package foundations (Fit **1–2**).

---

## Recommendation (executive)

**Compose-from-standards, not greenfield.**  
Ship **Analysis Package** as an **RO-Crate profile** with **PROV** responsibility/run semantics, **Table Schema/JSON Schema** contracts, **Web Annotation** labels, and **OpenLineage** as the live lineage projection. Invent only a thin `ap:` vocabulary and profile constraints. Optionally BagIt-wrap for custody and dual-export Croissant when packs are training-eligible.

This matches prior product-scan conclusion (“composition greenfield”) while maximizing reuse of mature W3C/IETF/community specs with real validators and extension mechanisms.
