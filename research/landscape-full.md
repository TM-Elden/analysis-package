# Analysis Package Landscape Research

**Date:** 2026-08-16  
**Thesis:** Supply-chain / FP&A planners' weekly analyses should be packaged as token capital — auditable, replayable, trainable — via an "analysis package" standard.  
**Target layout:** `MANIFEST` + `GUIDELINE.md` + `inputs/` + `code/` + `outputs/` + `labels/` + `qa/`  

**MUST concepts:** package_id/version, as_of, analyst+reviewer, purpose, output_contract, inputs (snapshot_id/source_system/as_of), method guideline version + entrypoint, engines (deterministic flag), outputs+schemas, labels (overrides/judgments/truths as JSONL), QA status+checks, intended_use/out_of_scope/confidentiality/training_eligibility, optional four-bucket context map.

**Scoring (0–5 closeness to full analysis-package):** how well the artifact covers the MUST list as a *portable, self-describing package of one analytical/planning run*, not just one subsystem.

---

## 1. MLOps dataset versioning

### DVC (Data Version Control)
- **What:** Git-like versioning for data/models/pipelines; `.dvc` metafiles in Git, content in remote cache.
- **URL:** https://dvc.org/ · https://doc.dvc.org/
- **Score:** 3
- **Covers well:** Input/output artifact versioning, code+data linkage, pipeline stages, reproducibility of ML experiments, open layout.
- **Misses:** No first-class analyst/reviewer, guideline versioning as labeling ops, overrides-as-labels JSONL, output_contract for planning KPIs, as_of/source_system planning semantics, training_eligibility/confidentiality cards, QA as human review gates.
- **Open source:** Yes (Apache-2.0)

### lakeFS
- **What:** Git-like version control *over* object stores/data lakes (branch/commit/merge/time-travel).
- **URL:** https://lakefs.io/ · https://docs.lakefs.io/
- **Score:** 2
- **Covers well:** Snapshot_id equivalents (commits), zero-copy branches for scenario isolation, rollback, scale.
- **Misses:** Not a run package; no method/guideline, labels, QA, cards, engines, analyst roles. Infrastructure under a package, not the package.
- **Open source:** Yes (Apache-2.0); commercial lakeFS Cloud/Enterprise

### Delta Lake time travel
- **What:** ACID table format with automatic versioning; read by version or timestamp.
- **URL:** https://delta.io/ · https://delta.io/blog/2023-02-01-delta-lake-time-travel/
- **Score:** 1–2
- **Covers well:** as_of / snapshot of tabular inputs/outputs; audit of table history.
- **Misses:** Single-table concern; no analysis unit, guidelines, labels, QA package, method versioning.
- **Open source:** Yes (Apache-2.0)

### Pachyderm
- **What:** Containerized data pipelines with automatic data versioning and lineage (commit-based repos).
- **URL:** https://github.com/pachyderm/pachyderm · HPE docs
- **Score:** 3
- **Covers well:** Versioned inputs→outputs, pipeline reproducibility, lineage, deterministic container runs.
- **Misses:** Planning-specific contracts, human labels/overrides, guideline docs, dataset-card ethics fields, analyst/reviewer workflow as first-class.
- **Open source:** Core open; enterprise offerings

---

## 2. Experiment tracking (artifacts)

### MLflow
- **What:** Open experiment tracking: params, metrics, artifacts per run; model registry.
- **URL:** https://mlflow.org/docs/latest/ml/tracking/
- **Score:** 3
- **Covers well:** package_id≈run_id, versioned artifacts (inputs/models/outputs), params as method knobs, replay via logged code/env (partial).
- **Misses:** Structured guideline versioning, labels JSONL as overrides, planning output_contract, intended_use/training_eligibility, human reviewer gates, snapshot_id/source_system taxonomy.
- **Open source:** Yes (Apache-2.0)

### Weights & Biases (W&B Artifacts)
- **What:** Experiment tracking + Artifacts for versioned datasets/models as run I/O.
- **URL:** https://docs.wandb.ai/models/artifacts · https://wandb.ai/site/artifacts/
- **Score:** 3
- **Covers well:** Artifact lineage across pipeline steps, versioning, metadata, collaboration UI.
- **Misses:** Same gaps as MLflow for planning/labeling/cards; proprietary SaaS center of gravity.
- **Open source:** Client open-ish; platform commercial

### Neptune
- **What:** Metadata store for ML runs (params, metrics, artifacts).
- **URL:** https://neptune.ai/
- **Score:** 2–3
- **Covers well:** Run metadata and artifacts.
- **Misses:** Portable on-disk package standard; planning/label/QA/card semantics.
- **Open source:** No (commercial; has had open client bits historically)

---

## 3. Data lineage / observability / catalogs

### OpenLineage + Marquez
- **What:** Open standard + reference implementation for job/dataset/run lineage events.
- **URL:** https://openlineage.io/ · https://marquezproject.ai/
- **Score:** 2
- **Covers well:** Job runs, dataset versions, inputs→outputs edges, observability.
- **Misses:** Not a package format; no guidelines, labels, QA checks bundle, cards, engines, human judgments.
- **Open source:** Yes

### DataHub / OpenMetadata / Amundsen
- **What:** Metadata platforms: catalog, lineage, ownership, sometimes DQ.
- **URL:** https://datahubproject.io/ · https://open-metadata.org/ · Amundsen
- **Score:** 2
- **Covers well:** Discovery, ownership, lineage graphs, some quality.
- **Misses:** Per-analysis portable bundle; method guidelines; override labels; training eligibility.
- **Open source:** Yes (all three core)

### Collibra
- **What:** Enterprise data governance catalog.
- **URL:** https://www.collibra.com/
- **Score:** 1–2
- **Covers well:** Governance, stewardship, policies.
- **Misses:** Analysis run packaging, replay, labels-as-training.
- **Open source:** No

---

## 4. Feature stores

### Feast / Tecton
- **What:** Serve point-in-time correct features for training/serving.
- **URL:** https://docs.feast.dev/ · https://www.tecton.ai/
- **Score:** 1
- **Covers well:** as_of / point-in-time joins (weak analog to input snapshots).
- **Misses:** Explicitly *not* full dataset/label versioning or experiment packages (Feast docs). Weak fit for weekly planner analyses.
- **Open source:** Feast yes; Tecton commercial

---

## 5. Analytical reproducibility & data packages

### Frictionless Data Package
- **What:** JSON descriptor (`datapackage.json`) + resources; schemas; optional README/scripts layout.
- **URL:** https://specs.frictionlessdata.io/data-package/
- **Score:** 4
- **Covers well:** Manifest (id, name, version, licenses, sources, contributors, resources+schemas), portable directory layout, scripts/, data/, README — closest *open packaging* primitive to MANIFEST+layout.
- **Misses:** Native concepts for as_of planning cuts, guideline version+entrypoint, engines/deterministic flag, labels/overrides JSONL, QA status+checks, output_contract, training_eligibility/confidentiality, reviewer workflow. Extensible via extra properties/profiles — would need an "analysis-package" profile.
- **Open source:** Yes (specs + libs)

### Quilt
- **What:** Versioned data packages on S3 with metadata, immutability, catalog UX (science/bio skew).
- **URL:** https://github.com/quiltdata/quilt · https://www.quilt.bio/
- **Score:** 3–4
- **Covers well:** Package as unit (data+metadata+version history), reproducibility, documentation, agent-oriented packaging narrative.
- **Misses:** Planning labels/overrides, guideline ops, QA gates, FP&A/SC domain contracts; AWS-centric.
- **Open source:** Yes (Apache-2.0) + commercial

### BagIt (RFC 8493)
- **What:** Hierarchical bag + checksum manifests for reliable transfer/preservation.
- **URL:** https://datatracker.ietf.org/doc/html/rfc8493
- **Score:** 2
- **Covers well:** Integrity, transfer, opaque payload packaging.
- **Misses:** Semantic analysis metadata (almost everything on MUST list beyond "files + checksums").
- **Open source:** Yes (IETF standard)

### R targets (successor to drake)
- **What:** Make-like reproducible analytical pipelines in R.
- **URL:** https://docs.ropensci.org/targets/
- **Score:** 3
- **Covers well:** Method as dependency graph, caching, reproducibility, deterministic rebuilds.
- **Misses:** Portable multi-language package standard, labels, cards, multi-system input snapshots, human review.
- **Open source:** Yes

### Dagster asset checks / Prefect / Airflow
- **What:** Orchestrators; Dagster assets + asset checks for DQ embedded in pipelines.
- **URL:** https://dagster.io/blog/dagster-asset-checks
- **Score:** 2–3
- **Covers well:** Materializations, checks/QA hooks, asset lineage, code versioning.
- **Misses:** Self-contained analysis package export; guideline labeling; training eligibility; planner roles.
- **Open source:** Yes (cores)

---

## 6. Model / dataset cards

### Datasheets for Datasets (Gebru et al., 2018)
- **What:** Academic questionnaire for dataset motivation, composition, collection, uses, distribution.
- **URL:** https://arxiv.org/abs/1803.09010
- **Score:** 3 (for the *card* slice only)
- **Covers well:** intended_use, out_of_scope, motivation, composition, collection — direct inspiration for package card fields.
- **Misses:** Runtime package, inputs snapshots, engines, labels stream, QA execution, replay.
- **Open source:** Paper/template (yes)

### Hugging Face Dataset Cards / Model Cards
- **What:** README+YAML documentation convention on the Hub.
- **URL:** https://huggingface.co/docs/hub/en/datasets-cards · Model cards (Mitchell et al.)
- **Score:** 3 (documentation slice)
- **Covers well:** Human-readable intended use, biases, licensing; pairs with versioned repos.
- **Misses:** Full analysis run structure (code/engines/labels/qa as first-class dirs).
- **Open source:** Yes (convention + hub)

### Google Model Cards
- **What:** Structured model documentation (performance, limitations).
- **URL:** https://modelcards.withgoogle.com/ (concept from Mitchell et al.)
- **Score:** 2–3
- **Covers well:** Intended use / limitations for *models*.
- **Misses:** Analysis/planning package; inputs/labels/QA packaging.

---

## 7. Decision / audit trails in planning (SC / FP&A)

### SAP IBP Change History
- **What:** Tracks changes to key figure values in planning areas; extractable via OData.
- **URL:** https://help.sap.com/docs/SAP_INTEGRATED_BUSINESS_PLANNING/… (Change History for Key Figures)
- **Score:** 2
- **Covers well:** Audit of value changes (who/when/what) — partial "labels/overrides" trail inside the system of record.
- **Misses:** No portable analysis package; no guideline versioning; no training export; no full input snapshot+method+QA bundle. Vendor-locked.
- **Open source:** No

### Anaplan
- **What:** Planning platform; scenarios, calculation engine, community patterns for approval + audit trail.
- **URL:** https://www.anaplan.com/ · community audit-trail patterns
- **Score:** 2
- **Covers well:** Scenario planning, deterministic calc engine narrative, some approval/audit patterns.
- **Misses:** No open "decision package" standard for export/train/replay outside Anaplan; no dataset-card/labeling ops.
- **Open source:** No

### Kinaxis (RapidResponse / Maestro)
- **What:** Concurrent supply-chain planning; fast what-if scenarios; collaboration.
- **URL:** https://www.kinaxis.com/
- **Score:** 2
- **Covers well:** Scenario isolation, consequence analysis, planner workflows.
- **Misses:** No public portable analysis-package format; no ML-training-oriented packaging of judgments.
- **Open source:** No

### DecisionLedger AI (and similar "decision audit" vendors)
- **What:** Decision governance / immutable decision audit trail layered on modeling tools.
- **URL:** https://decisionledgerai.com/compare/anaplan (example positioning)
- **Score:** 2–3
- **Covers well:** Decision audit, approvals, outcome tracking framing.
- **Misses:** Not a cross-vendor open standard; unclear full MUST coverage for training data packaging.
- **Open source:** No

**Finding:** No major SC/FP&A vendor markets a portable, open **"decision package" / "analysis package"** equivalent to a dataset card + DVC-style bundle. Change logs and scenarios stay *inside* the planning system.

---

## 8. Knowledge management for analysts

### Observable notebooks + Framework
- **What:** Reactive notebooks; data loaders; publishable data apps.
- **URL:** https://observablehq.com/ · Quarto OJS integration https://quarto.org/
- **Score:** 2–3
- **Covers well:** Narrative + code + data exploration; shareable analyses.
- **Misses:** Strict input snapshot contracts, labels/overrides, QA gates, training_eligibility packaging.

### Jupyter + Binder + repo2docker
- **What:** Repo → containerized reproducible notebook environment.
- **URL:** https://repo2docker.readthedocs.io/ · mybinder.org
- **Score:** 3
- **Covers well:** code/ + env replayability; good companion to a package's `code/`.
- **Misses:** Manifest semantics for planning MUST fields; labels; multi-system as_of inputs.

### Vertex AI Pipelines / Kubeflow / similar
- **What:** Managed ML/analytics pipelines with artifacts.
- **URL:** Google Vertex Pipelines docs
- **Score:** 2–3
- **Covers well:** Orchestrated runs, artifact lineage.
- **Misses:** Portable offline standard; planner labeling; cards.

---

## 9. Labeling / workforce platforms

### Scale AI
- **What:** Managed + platform labeling at scale; guidelines, QA, multi-review.
- **URL:** https://scale.com/
- **Score:** 3 (process inspiration)
- **Covers well:** Guideline-driven labeling, QA workflows, reviewer hierarchies — *operational* analog for "overrides as labels."
- **Misses:** Not packaged analytical runs for SC/FP&A; no open portable package standard; vision/LLM-data skew.
- **Open source:** No

### Labelbox
- **What:** Labeling platform, catalog, model-assisted labeling, evaluation.
- **URL:** https://labelbox.com/
- **Score:** 2–3
- **Covers well:** Annotation schema, QA, workforce.
- **Misses:** Analysis package for planning; open standard export as training capital for planner judgments.
- **Open source:** No

### Snorkel Flow
- **What:** Programmatic labeling, labeling functions, data-centric iteration, guidelines/IAA heritage from Snorkel research.
- **URL:** https://snorkel.ai/
- **Score:** 3
- **Covers well:** Versioned labeling logic, weak supervision, error analysis — closest *method* analog to "guideline version + labels."
- **Misses:** Full planning analysis bundle (inputs from ERP, engines, output_contract, confidentiality).
- **Open source:** Research Snorkel open; Flow commercial

**Finding:** No major platform markets **"analytics labeling"** for planner overrides/judgments as first-class training data packages. Inspiration is strong; product fit is greenfield.

---

## 10. Emerging context packs / agent memory / skills

### "Context packs" (various)
- **What:** Curated briefings/tools/prompts for agents (Ctxpack, blogware, AWS Greengrass agent context pack, ContextOS "deployable contract").
- **URLs:** e.g. https://www.ctxpack.com/docs/packs · assorted 2025–2026 posts
- **Score:** 2
- **Covers well:** Versioned context bundles for agents; optional resemblance to four-bucket context map.
- **Misses:** Analytical reproducibility, QA, labels-as-truth, planning output contracts.

### Skill packages (agent tooling)
- **What:** Bundled instructions + files extending agents (Hermes skills, Claude skills, etc.).
- **Score:** 1–2
- **Covers well:** Method/entrypoint packaging for agents.
- **Misses:** Data snapshots, labels, QA, training eligibility for *human planner runs*.

### Oracle AI Agent Memory (example enterprise memory)
- **What:** Governed short/long-term agent memory package.
- **URL:** Oracle blogs / pypi oracleagentmemory
- **Score:** 1–2
- **Misses:** Analysis-run packaging for FP&A.

---

## 11. Open standards (deep)

### RO-Crate (Research Object Crate)
- **What:** Lightweight JSON-LD (schema.org) package of research data, software, workflows, provenance; `ro-crate-metadata.json` in a directory/crate.
- **URL:** https://www.researchobject.org/ro-crate/ · https://doi.org/10.3233/DS-210053
- **Score:** 4–5 (highest *structural* match among open standards)
- **Covers well:** Self-describing package; inputs/outputs/tools/people; provenance; workflows; extensible profiles; FAIR; can record entire analysis. Closest academic/open cousin to analysis-package layout + manifest.
- **Misses:** Domain vocabulary for SC/FP&A (as_of planning cuts, override labels JSONL convention, training_eligibility, output_contract for plan KPIs, deterministic engine flags). Would need an **RO-Crate profile** (like workflow RO-Crate) rather than greenfield binary.
- **Open source:** Yes (Apache-2.0 spec/community)

### Croissant (MLCommons)
- **What:** JSON-LD metadata for ML-ready datasets (resources, structure, ML semantics, responsible ML).
- **URL:** https://github.com/mlcommons/croissant · https://mlcommons.org/2024/03/croissant_metadata_announce/
- **Score:** 3–4
- **Covers well:** Dataset metadata, files, schemas/recordSets, responsible-use fields; HF/Kaggle/Google adoption; trainable-data orientation.
- **Misses:** Single *analysis run* (method+engines+human overrides+QA) — oriented to static/versioned *datasets*, not weekly planning executions. Can describe label files but not planner workflow.
- **Open source:** Yes (Apache-2.0 impl; spec CC BY-ND)

### DCAT (W3C)
- **What:** RDF vocabulary for data catalogs (datasets, distributions, services).
- **URL:** https://www.w3.org/TR/vocab-dcat-3/
- **Score:** 2
- **Covers well:** Catalog-level discovery metadata.
- **Misses:** Run packaging, method, labels, QA.

### PROV-O (W3C)
- **What:** Ontology for provenance: entities, activities, agents.
- **URL:** https://www.w3.org/TR/prov-o/
- **Score:** 3 (as *substrate*)
- **Covers well:** analyst/reviewer as agents, generation/use of entities, activity timing — formal backbone for as_of + who did what.
- **Misses:** Concrete package layout, guidelines, QA checks schema, training eligibility.
- **Open source:** Yes (W3C)

### BagIt + Frictionless + RO-Crate comparison (packaging trio)
| Standard     | Layout strength | Semantic depth | ML/train fit | Analysis-run fit |
|-------------|-----------------|----------------|--------------|------------------|
| BagIt       | High (integrity)| Low            | Low          | Low              |
| Frictionless| High            | Medium         | Medium       | Medium–High w/ profile |
| RO-Crate    | High            | High (LD/PROV) | Medium       | **Highest**      |
| Croissant   | Medium (meta)   | High for ML DS | **Highest**  | Medium           |

---

## Scored hit list (compact)

| Name | One-liner | URL | Score | OS? |
|------|-----------|-----|-------|-----|
| RO-Crate | Research object package (data+software+prov) JSON-LD | researchobject.org/ro-crate | **4–5** | Y |
| Frictionless Data Package | datapackage.json + resources/schemas layout | specs.frictionlessdata.io | **4** | Y |
| Croissant | ML-ready dataset metadata (MLCommons) | github.com/mlcommons/croissant | **3–4** | Y |
| Quilt | Versioned S3 data packages + catalog | quilt.bio / github.com/quiltdata/quilt | **3–4** | Y |
| DVC | Git-for-data + pipelines | dvc.org | **3** | Y |
| MLflow / W&B | Experiment runs + artifacts | mlflow.org / wandb.ai | **3** | Y / mixed |
| Pachyderm | Versioned data + container pipelines | github.com/pachyderm/pachyderm | **3** | Y |
| Datasheets / HF cards | Documentation for intended use | arxiv 1803.09010 / HF docs | **3** | Y |
| Snorkel / Scale / Labelbox | Guideline+label+QA ops | snorkel.ai / scale.com / labelbox.com | **3** process | N/mix |
| targets (R) | Reproducible analysis pipelines | docs.ropensci.org/targets | **3** | Y |
| PROV-O | Provenance ontology | w3.org/TR/prov-o | **3** substrate | Y |
| OpenLineage/Marquez | Job/dataset lineage standard | openlineage.io | **2** | Y |
| lakeFS / Delta | Lake/table time travel | lakefs.io / delta.io | **2** | Y |
| Dagster checks | Asset DQ in orchestrator | dagster.io | **2–3** | Y |
| Binder/repo2docker | Env replay for notebooks | repo2docker.readthedocs.io | **3** env only | Y |
| SAP IBP / Anaplan / Kinaxis | Planning systems + change/scenario | vendor sites | **2** | N |
| Feast | Feature store PIT joins | feast.dev | **1** | Y |
| Context/skill packs | Agent context bundles | various | **1–2** | mix |
| BagIt | Checksummed bag transfer | RFC 8493 | **2** | Y |
| DCAT | Catalog vocabulary | w3.org/TR/vocab-dcat-3 | **2** | Y |

---

## (A) Closest 5 products/standards

1. **RO-Crate** — Best structural + provenance match; extend via domain profile.  
2. **Frictionless Data Package** — Best simple manifest+directory match; extend via custom profile.  
3. **Croissant** — Best *training-data metadata* alignment for eligibility/features/labels files.  
4. **DVC + (MLflow|W&B)** — Best practical MLOps stack for versioned I/O + run replay (compose, don't adopt as standard).  
5. **Quilt** — Best commercial/OSS "package as product" UX for versioned data+docs (science skew).

**Process inspirations (not package standards):** Scale/Snorkel labeling ops; Datasheets/HF cards; SAP/Anaplan change+scenario *semantics* (not formats).

---

## (B) White space / greenfield claim strength

**Claim strength: HIGH for the *intersection*, MEDIUM for individual pieces.**

- Individual capabilities exist: versioned data (DVC/lakeFS/Delta), run artifacts (MLflow), packages (Frictionless/RO-Crate/Quilt), cards (Datasheets/HF), lineage (OpenLineage), labels (Scale/Snorkel), planning audit (IBP change history).
- **Nobody productizes the full MUST stack as a portable standard aimed at supply-chain/FP&A planning runs** where:
  - human overrides/judgments are first-class **labels** (JSONL),
  - method **guidelines** are versioned like labeling guidelines,
  - **output_contract** + engines (deterministic flag) define the plan artifact,
  - **training_eligibility / confidentiality** gate reuse as token capital,
  - package is the unit of audit + replay + future model training.
- SC/FP&A vendors keep decision context **inside** closed systems; ML packaging standards ignore **planner workflow**.
- Greenfield is the **domain profile + operational loop**, not inventing packaging from zero.

---

## (C) Build-on vs build-new recommendation

**Recommend: BUILD-ON (profile + layout convention), not pure greenfield binary format.**

1. **Base packaging:** RO-Crate *or* Frictionless Data Package  
   - Prefer **RO-Crate** if Linked Data/PROV/people/workflow matter for audit.  
   - Prefer **Frictionless** if JSON-simple + tabular schemas + low LD overhead matter for FP&A engineers.
2. **Layout convention (your dirs):** Map to crate/package resources: `GUIDELINE.md`, `inputs/`, `code/`, `outputs/`, `labels/*.jsonl`, `qa/`.
3. **Card fields:** Lift Datasheets/HF sections → `intended_use`, `out_of_scope`, `confidentiality`, `training_eligibility`.
4. **ML export path:** Optional Croissant projection of `labels/` + selected inputs/outputs for HF/training pipelines.
5. **Runtime glue (not the standard):** DVC or lakeFS for large snapshots; MLflow/W&B optional for metrics UI; OpenLineage events optional emitters; Binder/repo2docker for `code/` replay.
6. **Do not wait for** SAP/Anaplan/Kinaxis to open a standard — treat them as **source_system** connectors that *emit* analysis packages.
7. **Spec work:** Publish `analysis-package` profile (JSON Schema or RO-Crate profile) with MUST fields; reference PROV-O agents for analyst/reviewer.

**Avoid:** New checksum bag format alone (BagIt already); new lineage bus (OpenLineage exists); competing with full MLOps platforms.

---

## (D) Supply-chain-specific tools

| Tool | Role vs analysis-package |
|------|---------------------------|
| **SAP IBP** | System of record; key-figure **change history** ≈ partial override audit; no portable package export standard found. |
| **Anaplan** | Scenarios + calc engine; community approval/audit patterns; closed. |
| **Kinaxis** | Concurrent planning, what-ifs; no open decision-package format found. |
| **o9, Blue Yonder, Coupa Supply Chain, etc.** | Same pattern: in-app scenario/audit, not open analysis packages (not deeply re-verified per vendor in this pass; no public "analysis package" standard surfaced in search). |
| **Decision governance add-ons** (e.g. DecisionLedger-class) | Decision audit narrative; vendor-specific. |

**SC-specific gap:** Planning systems optimize *live plan quality* and *in-app audit*, not *exportable training capital* from weekly analytical judgment. That gap is the product thesis.

---

## Mapping MUST concepts → existing coverage

| MUST concept | Best existing coverage | Gap |
|--------------|------------------------|-----|
| package_id/version | Frictionless, RO-Crate, DVC, Quilt, MLflow run_id | — |
| as_of | Delta/lakeFS time travel; PIT features; PROV time | Not standard on analysis package |
| analyst+reviewer | PROV-O agents; RO-Crate people; Scale reviewers | Not in SC export formats |
| purpose | Datasheets motivation; HF cards | — |
| output_contract | Weak: Frictionless schemas; OpenAPI-ish customs | Planning KPI contracts missing |
| inputs snapshot_id/source/as_of | DVC/lakeFS/Delta + lineage | Multi-system planning taxonomy |
| method guideline version + entrypoint | Snorkel/Scale guidelines; targets/DVC stages; skills | Not unified with data package |
| engines + deterministic flag | Pachyderm/containers; MLflow env; RO-Crate software | Flag rarely first-class |
| outputs+schemas | Frictionless/Croissant/RO-Crate | — |
| labels overrides JSONL | Labeling platforms; custom | **Not standard for planner overrides** |
| qa status+checks | Scale QA; Dagster checks; GE | Not bundled in analysis package standard |
| intended_use / OOS / confidentiality / training_eligibility | Datasheets, HF, Croissant RAI | **training_eligibility underused outside ML hubs** |
| four-bucket context map | Context packs (loose) | No standard |

---

## Primary citations (selected)

- DVC: https://dvc.org/  
- lakeFS: https://docs.lakefs.io/  
- Delta time travel: https://delta.io/blog/2023-02-01-delta-lake-time-travel/  
- OpenLineage: https://openlineage.io/  
- Marquez: https://marquezproject.ai/  
- MLflow Tracking: https://mlflow.org/docs/latest/ml/tracking/  
- W&B Artifacts: https://docs.wandb.ai/models/artifacts  
- Frictionless Data Package: https://specs.frictionlessdata.io/data-package/  
- BagIt RFC 8493: https://datatracker.ietf.org/doc/html/rfc8493  
- Quilt: https://github.com/quiltdata/quilt  
- RO-Crate: https://www.researchobject.org/ro-crate/ · packaging paper https://doi.org/10.3233/DS-210053  
- Croissant: https://github.com/mlcommons/croissant · MLCommons announce  
- Datasheets: https://arxiv.org/abs/1803.09010  
- HF Dataset Cards: https://huggingface.co/docs/hub/en/datasets-cards  
- PROV-O: https://www.w3.org/TR/prov-o/  
- DCAT3: https://www.w3.org/TR/vocab-dcat-3/  
- targets: https://docs.ropensci.org/targets/  
- Dagster asset checks: https://dagster.io/blog/dagster-asset-checks  
- Feast limitations: https://docs.feast.dev/  
- SAP IBP change history: SAP Help "Change History for Key Figures"  
- Anaplan / Kinaxis: vendor marketing + community audit patterns  
- Snorkel Flow / Scale / Labelbox: vendor sites  

---

## Bottom line

**Exists:** packaging formats, data versioning, experiment runs, dataset cards, lineage buses, labeling ops, in-app planning audit.  
**Does not exist (as open standard + SC/FP&A product):** the full **analysis package** that makes a planner's weekly run simultaneously auditable, replayable, and training-eligible.  
**Strongest path:** RO-Crate or Frictionless **profile** + Datasheets-style card + labels/qa conventions + connectors from IBP/Anaplan/Kinaxis/data lakes — not a from-scratch universe.
