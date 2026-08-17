# Analysis Package Standard (draft v0.2)

> **Canonical home:** `fathm` repo · `standard/ap-0.2/`.  
> **Product brand:** **fathm** - understand fully, down to its source (`brand/BRAND.md`).  
> Product pitch and architecture: `brand/PITCH.md`, `docs/ARCHITECTURE.md`.

## Status and intent

**This is a formal interchange contract**, not an optional research notebook format.

Every **planning agent** that pair-codes / plans **with a human planner** MUST emit and consume work in Analysis Package form for each planning cycle (or equivalent bounded run). Human planners remain accountable for judgment; the package is how that work becomes **portable token capital** - auditable, replayable, and eligible for training under policy.

| Audience | Obligation |
|----------|------------|
| **Planning agents** (harness + model + tools) | Produce valid packages; refuse "done" without package completeness gates |
| **Human planners** | Own judgments, truths, overrides, and sign-off; do not leave meaning only in chat or cell paint |
| **Platform / team leads** | Version guidelines, reason codes, ontologies; run validators and gold checks |
| **Downstream (audit, ML, teammates)** | May rely only on package contents + declared contracts - not on tribal side channels |

Foundation (research): RO-Crate profile + PROV + Table/JSON Schema + Web Annotation for labels; thin `ap:` domain vocab. See `research/findings.md` / `research/standards-foundation.md`.

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

## Standard purposes

The Analysis Package shape is intentionally multi-purpose. One enforced metadata contract supports:

1. **Lineage / provenance** - inputs, method, outputs, human deltas  
2. **Reproducibility** - pins, versions, explicit overrides  
3. **Portability** - same unit across agents and tools  
4. **Governance** - gate defines "done" / published  
5. **Credit** - authors on judgments  
6. **Opt-in training/eval corpus** - structured examples when `training_eligibility` allows (default false)  
7. **Later query/RAG** - only over packages that passed the gate  

See `docs/VISION.md`.


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
2. **Additional properties** on the manifest are allowed (`x-` or profile-namespaced). Validators MUST ignore unknown fields unless `validation_mode: strict` is set. (v0.2.1: this switch was renamed from `profile: strict` - that name collided with the MUST field `profile`, which carries a profile identifier like `commodity_commit_forecast/0.1`, not a validation mode. See changelog.)  
3. **Pack types** (commit_pack, demand_consensus, ...) are profiles that add typed checks and reason_code sets - they MUST NOT remove core MUST fields. Profile-specific requirements (extra required output_contract names, reason-code allow-lists) live in per-profile machine files under `profiles/<name>/`, never forked into the core manifest schema.  
4. **New input kinds** = new input resource + schema, not a fork of the standard.  
5. **New logic** = `code/` + guideline bump, not side-channel scripts outside the package.

---

## Minimum viable metadata (MUST)

> **v0.2.1 editorial reconciliation note:** this table was amended alongside the first `manifest.schema.json` build to resolve seven discrepancies found between this table, the L1 implementation plan (`docs/DESIGN-FATHM-MVP.md`), and the reference example (`examples/commodity-commit-v1/`). See changelog below for the itemized list. The schema is the enforced expression of this table; when the two ever disagree, this table is authoritative and the schema has a bug.

| Field | Type | Why |
|-------|------|-----|
| `package_id` | string (uuid/ulid) | Stable identity |
| `package_version` | semver or content-hash | Versioning |
| `standard_version` | e.g. `ap/0.2` | Contract version the pack claims |
| `profile` | string, `<name>/<version>` (e.g. `commodity_commit_forecast/0.1`) | Which pack-type profile this package conforms to |
| `title` | string | Human name |
| `created_at` / `as_of` | ISO-8601 | Temporal truth |
| `owners.analyst` | id + role | Human planner of record |
| `owners.reviewer` | id or null | Reviewer |
| `owners.agent` | id/harness/model hash or null | Pair agent identity if any (MUST be present as a field; MAY be null when no agent paired) |
| `purpose` | string | Why this pack exists |
| `output_contract` | list of {name, consumer, format, path, schema_ref} | Definition of done (inversion); `path` is the artifact location checked by the gate |
| `inputs[]` | list | Provenance of each raw item |
| `inputs[].snapshot_id` or `external_ref` | string | Pin or escape hatch |
| `inputs[].source_system` | string | ERP, sheet, API, ... |
| `inputs[].as_of` | datetime | Lineage |
| `method.guideline_version` | string | Versioned instructions |
| `method.summary` | string | Short how |
| `method.entrypoint` | path or command | Replay hook |
| `labels.overrides_path` | path to jsonl | Hard deltas with reason_code |
| `labels.judgments_path` | path to jsonl | Soft overlays |
| `labels.truths_applied_path` | path to jsonl | Planner truths / rules used |
| `engines[]` | {name, version, deterministic} | Compute / rule modules |
| `qa.status` | draft\|in_review\|approved\|rejected | Gate |
| `qa.checks[]` | {name, result, evidence} | Validators; MUST be present once `qa.status` is `in_review` or `approved` (a fresh `draft` package has no gate history yet, so it is not required there) |
| `intended_use` | string | Allowed use |
| `out_of_scope` | string | Misuse fence |
| `confidentiality` | string (free-form in v0; profiles MAY constrain to an enum) | Distribution |
| `training_eligibility` | bool | Token capital policy; opt-in, default false (D7) |

`training_eligibility_reason` (string) is SHOULD, not MUST - explains the `training_eligibility` value but its absence does not fail the gate.

`outputs[]` (paths + schema_ref) MAY also be present as a convenience mirror of `output_contract`'s artifact-facing fields; it is not independently required and validators MUST NOT treat it as a second source of truth - `output_contract[].path` is authoritative for the gate.

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
  "field_path": "supplier_forecast.ACME.BBU-100.week_36_qty",
  "before": 1000,
  "after": 700,
  "reason_code": "HOLD_FOR_PRICE_NEGOTIATION",
  "reason_text": "optional",
  "bucket": 3,
  "evidence_refs": ["inputs/supplier_splits.csv#rows=part:BBU-100"],
  "author": "planner_or_agent_id",
  "ts": "2026-08-16T16:40:00Z",
  "agent_draft": {
    "reason_code": "HOLD_FOR_PRICE_NEGOTIATION",
    "reason_text": "optional - the pair agent's draft suggestion before the human's final edit"
  }
}
```

Enforced by the gate's `labels_row_shape` check against `standard/ap-0.2/schemas/override-row.schema.json`
(v0.2.2 addition): `override_id`, `field_path`, `before`, `after`, `reason_code`, `author`, and `ts` are
required; `reason_text` and `evidence_refs` stay optional in core - a "training-grade" profile MAY
require `reason_text` (see `profiles/<name>/training_grade.json`). `field_path`'s segment grammar
(e.g. the `supplier_forecast.<supplier>.<part>.week_<n>_qty` shape above) is declared per profile in
`profiles/<name>/field_path_grammar.json`, resolved by `ap_gate.field_path.resolve_field_path` - this
makes `field_path` mechanically resolvable to output-schema key columns instead of free text.

`evidence_refs` entries MAY carry an optional `#rows=<column>:<value>[,<column>:<value>...]` fragment
pointing at a specific slice of the referenced input file instead of the whole file (e.g.
`inputs/supplier_splits.csv#rows=part:BBU-100`) - SHOULD, never MUST; a plain whole-file ref (no
fragment) and external refs (`contracts://...`) remain valid unchanged. Parsed by
`ap_gate.evidence_refs.parse_evidence_ref`.

`agent_draft` (optional, v0.2.2 addition) captures the pair agent's draft `reason_code`/`reason_text`
before the human's accepted override landed in this row - opt-in, covered by the same
`training_eligibility` policy as the rest of the package. The gate's `agent_draft_present` check flags
(advisory by default; a training-grade profile MAY escalate to required) an override row missing
`agent_draft` when the package declares agent participation (`model_run.role`, C8).

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

Breaking changes only on major `ap/N`. Editorial reconciliation passes that clarify or fill gaps in the MUST table without removing or narrowing a MUST field are minor/patch (`ap/0.2.x`) and do not require HITL machinery pre-1.0 - a single-author commit with a changelog note is sufficient (see D6, D8).

### Changelog

**v0.2.2** (this pass) - training-export additions, additive/SHOULD only, no MUST field removed or narrowed:
1. Added a normative `override-row.schema.json` for every `labels/overrides.jsonl` row, enforced by
   the new `labels_row_shape` gate check; `reason_text` stays optional in core, required only via a
   profile's `training_grade.json` opt-in.
2. Added a per-profile `field_path_grammar.json` declaring how `field_path` segments map to
   output-schema key columns, resolved by `ap_gate.field_path.resolve_field_path`.
3. Allowed an optional `#rows=<column>:<value>[,...]` fragment on `evidence_refs` entries, pointing at
   a slice of an input file instead of the whole file - SHOULD, never MUST.
4. Added an optional `agent_draft: {reason_code, reason_text}` sub-object to the override row,
   capturing the pair agent's draft before the human's accepted edit; the new `agent_draft_present`
   gate check flags (advisory by default) a missing one when `model_run.role` shows agent
   participation. Same `training_grade.json` opt-in escalates it to required.

**v0.2.1** - editorial reconciliation, no MUST field removed or narrowed:
1. Added `profile` to the MUST table (it was required by the L1 implementation plan and by `reason_codes_known`, but missing from this table).
2. Renamed the `profile: strict` extensibility switch to `validation_mode: strict` - it collided with the `profile` field, which carries a profile identifier, not a validation mode.
3. Renamed `labels.overrides` / `labels.judgments` / `labels.truths_applied` to `labels.overrides_path` / `labels.judgments_path` / `labels.truths_applied_path`, matching the reference example and the L1 plan.
4. Split `training_eligibility` (bool, MUST) from `training_eligibility_reason` (string, SHOULD) instead of one combined "bool + reason" MUST row.
5. Clarified `qa.checks[]` is MUST only from `in_review` onward - a fresh `draft` package has no gate history yet.
6. Clarified `owners.agent` MUST be present as a field and MAY be null (was ambiguous "or null" phrasing read as optional-field).
7. Clarified `confidentiality` is a free-form string in v0 (no enum values were ever defined); an enum MAY be added later, and profiles MAY constrain it sooner.
8. Added `path` to `output_contract` entries (the L1 plan and the reference example both carry it; this table previously omitted it) and clarified the separate `outputs[]` array some packages carry is a non-authoritative convenience mirror, not a second MUST list.
9. Fixed broken `meta/...` related-file links below to the paths that actually exist in this repo (`research/`, not `meta/`).

## Related files

- `standard/ap-0.2/manifest.example.yaml`  
- `research/findings.md`  
- `research/standards-foundation.md`  
- Blog series: token capital, inversion, four buckets, harden ladder  
