# Analysis Package Standard (draft v0.2)

> **Canonical home:** this file lives in the `analysis-package` repo under `standard/ap-0.2/`.  
> Product pitch and architecture: `docs/PITCH.md`, `docs/ARCHITECTURE.md`.

## Status and intent

**This is a formal interchange contract**, not an optional research notebook format.

Every **planning agent** that pair-codes / plans **with a human planner** MUST emit and consume work in Analysis Package form for each planning cycle (or equivalent bounded run). Human planners remain accountable for judgment; the package is how that work becomes **portable token capital** - auditable, replayable, and eligible for training under policy.

| Audience | Obligation |
|----------|------------|
| **Planning agents** (harness + model + tools) | Produce valid packages; refuse "done" without package completeness gates |
| **Human planners** | Own judgments, truths, overrides, and sign-off; do not leave meaning only in chat or cell paint |
| **Platform / team leads** | Version guidelines, reason codes, ontologies; run validators and gold checks |
| **Downstream (audit, ML, teammates)** | May rely only on package contents + declared contracts - not on tribal side channels |

Foundation (research): RO-Crate profile + PROV + Table/JSON Schema + Web Annotation for labels; thin `ap:` domain vocab. See `meta/research/2026-08-16-analysis-package-findings.html` / standards foundation doc.

---

## Design goals (non-negotiable)

| Goal | Meaning |
|------|---------|
| **Portable** | A package is a self-contained directory (or BagIt/RO-Crate wrap) that moves across laptops, repos, and orgs without the original chat session or suite license. |
| **Deterministic core** | Given the same pinned inputs, method version, engine versions, and recorded overrides, **regeneration of engine outputs is bit- or schema-stable** within declared tolerances. Non-determinism is allowed only where declared (e.g. model-assisted draft) and MUST be isolated from deterministic engines. |
| **Extensible** | Unknown fields, extra resources, and profile extensions are allowed. Validators enforce **MUST** set only; additional method-specific logic lives in `code/` + guideline, not by forking the contract. |
| **Universal fit (within reason)** | The contract describes **any** planning process as: declared outputs, declared inputs, method, engines/rules, labels (overrides/judgments/truths), QA. It does **not** prescribe one BOM model, one ERP, or one forecast math. |

### What "no one can complain it doesn't fit" means

The standard is **process-shaped**, not **domain-shaped**:

```
outputs (contract) <- method/engines/rules <- inputs (snapshots)
                         ^
                   labels (human deltas)
                         ^
                        QA
```

If a planner can name what they deliver, what they consumed, how they transformed it, and what they overrode, **it fits**.  
If they cannot name those, the process is not ready for an agent pair - that is a readiness failure, not a format failure.

**In scope examples:** commodity commit packs, demand consensus, supply plans, exception packs, aging, NPI bridges, FP&A flash with model+overlay, multi-file Excel that collapses to one pattern.

**Out of scope (format does not try to be):** replacing the ERP, encoding every LTA clause as master data on day one, real-time APS optimization inside the crate.

**Escape hatch (still compliant):**  
If something truly cannot be snapshotted, declare it as an input with `availability: external_ref` + `access_procedure` + `as_of` best-effort, and put residual uncertainty in `labels.judgments[]`. Silent hardcodes remain **non-compliant**.

---

## Mental model

```
raw inputs (snapshots)  +  method (versioned guidelines)
        ->  transforms / engines / rules
        ->  outputs (the pack)
        ->  judgments & overrides (labels)
        ->  QA / review
        ->  package manifest
```

An **analysis package** is one bounded unit of planning work a teammate, auditor, or model could replay or learn from - not a naked xlsx and not a chat log.

---

## Normative keywords

MUST / MUST NOT / SHOULD / MAY as in RFC 2119.

---

## Agent contract (pair-programming / pair-planning)

When an agent assists a human planner, the agent MUST:

1. **Open or create** a package for the active cycle before mutating outputs.
2. **Record every input** it reads with `snapshot_id` (or external_ref escape hatch).
3. **Pin method** via `guideline_version` + entrypoint/commit.
4. **Route math** through declared `engines[]` (or explicit rule modules) with `deterministic: true|false`.
5. **Write every human or agent override** to `labels/` (never only into a cell without a label row).
6. **Emit outputs** only under paths listed in `output_contract`.
7. **Run QA checks** declared for the pack type; set `qa.status` honestly.
8. **Refuse "final" / "ship to consumer"** if MUST fields or QA gates fail - surface a machine-readable deficiency list.
9. **Stay portable:** no dependency on live chat memory as source of truth after the turn ends.

Humans MAY edit Sheets/Excel as UI; agents MUST still materialize package exports + labels.

---

## Determinism rules

| Layer | Rule |
|-------|------|
| Inputs | MUST be pinned (bytes hash and/or snapshot_id + as_of). |
| Engines with `deterministic: true` | Same inputs + config => same outputs within `qa.tolerances` if declared. |
| Engines with `deterministic: false` | MUST set flag; outputs are advisory until human accepts into labels/outputs. |
| Models / agents | MUST NOT be the only implementation of bucket-4 planning math. Model drafts become labels or accepted outputs via explicit write. |
| Replay | `repro.command` SHOULD regenerate deterministic slices; document non-replayable slices. |

---

## Extensibility rules

1. **MUST** fields stay stable across minor versions of this standard.  
2. **Additional properties** on the manifest are allowed (`x-` or profile-namespaced). Validators MUST ignore unknown fields unless `profile: strict`.  
3. **Pack types** (commit_pack, demand_consensus, ...) are profiles that add typed checks and reason_code sets - they MUST NOT remove core MUST fields.  
4. **New input kinds** = new input resource + schema, not a fork of the standard.  
5. **New logic** = `code/` + guideline bump, not side-channel scripts outside the package.

---

## Minimum viable metadata (MUST)

| Field | Type | Why |
|-------|------|-----|
| `package_id` | string (uuid/ulid) | Stable identity |
| `package_version` | semver or content-hash | Versioning |
| `standard_version` | e.g. `ap/0.2` | Contract version the pack claims |
| `title` | string | Human name |
| `created_at` / `as_of` | ISO-8601 | Temporal truth |
| `owners.analyst` | id + role | Human planner of record |
| `owners.reviewer` | id or null | Reviewer |
| `owners.agent` | id/harness/model hash or null | Pair agent identity if any |
| `purpose` | string | Why this pack exists |
| `output_contract` | list of {name, consumer, format, schema_ref} | Definition of done (inversion) |
| `inputs[]` | list | Provenance of each raw item |
| `inputs[].snapshot_id` or `external_ref` | string | Pin or escape hatch |
| `inputs[].source_system` | string | ERP, sheet, API, ... |
| `inputs[].as_of` | datetime | Lineage |
| `method.guideline_version` | string | Versioned instructions |
| `method.summary` | string | Short how |
| `method.entrypoint` | path or command | Replay hook |
| `outputs[]` | paths + schema_ref | Artifacts |
| `labels.overrides` | path to jsonl | Hard deltas with reason_code |
| `labels.judgments` | path to jsonl | Soft overlays |
| `labels.truths_applied` | path to jsonl | Planner truths / rules used |
| `engines[]` | {name, version, deterministic} | Compute / rule modules |
| `qa.status` | draft\|in_review\|approved\|rejected | Gate |
| `qa.checks[]` | {name, result, evidence} | Validators |
| `intended_use` | string | Allowed use |
| `out_of_scope` | string | Misuse fence |
| `confidentiality` | enum | Distribution |
| `training_eligibility` | bool + reason | Token capital policy |

`four_bucket_map` SHOULD be present; pack-type profiles MAY require it.

---

## Strongly recommended (SHOULD)

| Field | Why |
|-------|-----|
| `ontology_version` | Shared dictionary |
| `gold_reference_package_id` | Regression target |
| `repro.command` / `repro.environment` | One-command deterministic replay |
| `model_run` | harness, model id, prompt/tool hash (not full chat) |
| `edge_cases[]` | Living guideline fuel |
| `change_log[]` | Diff vs prior cycle |
| `tolerances` | Numeric replay windows |

---

## On-disk layout (portable unit)

```
analysis_packages/<package_id>_<title_slug>_v<version>/
  MANIFEST.yaml              # or ro-crate-metadata.json (profile)
  GUIDELINE.md               # method card
  inputs/
  code/                      # or immutable repo ref + lockfile
  outputs/
  labels/
    overrides.jsonl
    judgments.jsonl
    truths_applied.jsonl
  qa/
    checks.json
  # optional: provenance/, openlineage/, bagit wrap
```

---

## Override label row (normative shape)

```json
{
  "override_id": "...",
  "field_path": "supplier_forecast.ACME.week_36_qty",
  "before": 1000,
  "after": 700,
  "reason_code": "HOLD_FOR_PRICE_NEGOTIATION",
  "reason_text": "optional",
  "bucket": 3,
  "evidence_refs": ["inputs/..."],
  "author": "planner_or_agent_id",
  "ts": "2026-08-16T16:40:00Z"
}
```

If it is not in `labels/` or produced by a declared deterministic engine from pinned inputs, **it does not exist** for audit or training.

---

## Completeness gate (machine-checkable)

A package MAY be marked `qa.status: approved` only if:

1. All MUST fields present and type-valid  
2. Every `output_contract` entry has a corresponding output artifact  
3. Every file read by `method.entrypoint` is listed under `inputs[]` or vendored under `code/`  
4. `engines` with deterministic true have version pins  
5. Zero unexplained numeric edits (diff outputs vs engine regeneration ⊆ labels.overrides)  
6. Declared `qa.checks` all `pass` or waived with reason in qa  

Agents MUST run this gate (or subset) before claiming the planning turn finished.

---

## Fit test (for skeptics)

Ask the planner or agent to fill one page:

1. What do we deliver and who consumes it?  
2. What did we read (name + as-of)?  
3. What math/rules ran (name + version)?  
4. What did a human change and why (reason codes)?  
5. How would a teammate re-run this Monday?

If those answers exist, the process **fits the standard**.  
If not, fix the process - do not fork the format.

---

## Non-goals

- One global planning algorithm  
- Forbidding Excel/Sheets as interactive UI  
- Full master-data perfection before packaging  
- Storing entire agent transcripts as the system of record  

---

## Versioning of this standard

- **ap/0.2** - contract framing: mandatory agent pair format; portability, determinism, extensibility, universal process fit  
- Prior: ap/0.1 semantic field list  

Breaking changes only on major `ap/N`.

---

## Related files

- `meta/templates/analysis-package-manifest.example.yaml`  
- `meta/research/2026-08-16-analysis-package-findings.md`  
- `meta/research/2026-08-16-analysis-package-standards-foundation.md`  
- Blog series: token capital, inversion, four buckets, harden ladder  
