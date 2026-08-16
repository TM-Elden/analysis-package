# fathm - Full System Design (firstmate handoff)

**Handoff ID:** `fathm-system-2026-08-16`  
**To:** firstmate / captain (PiSD)  
**From:** Hermes  
**Repo:** https://github.com/TM-Elden/fathm  
**Pi clone:** `~/firstmate/projects/fathm`  
**Pi bundle:** `~/firstmate/data/portfolio-build/fathm-mvp/` (name retained; content is full system)

**Phasing, milestones, and cut lines are firstmate's call.** This doc defines *what the system is*, constraints, interfaces, and acceptance of a complete product - not a Hermes-mandated build order.

---

## 1. Product identity

| Name | Role |
|------|------|
| **fathm** | Product / company. *v.* understand something fully, down to its source. |
| **Analysis Package (ap)** | Format + standard. Portable unit of published analysis. |
| **ap-gate** | Preferred CLI/library name for validation (format-neutral). |

**Tagline:** Understand every analysis fully, down to its source.  
**Support line:** Powered by the Analysis Package standard.

Do not rename normative format identifiers to "fathm package" - brand and format stay distinct.

---

## 2. Mission

fathm makes AI-assisted planning and finance/ops analysis **trustworthy to publish**: every conclusion is traceable to pinned data, versioned method, labeled human deltas, and a gate - then searchable and governable across the org via bots, with humans still owning standard evolution.

---

## 3. System map (all in scope)

```
                    Human planner  +  Planning agent(s)
                              │
                              │  emit / update
                              v
                 ┌────────────────────────────┐
                 │    Analysis Package (ap)   │
                 │  inputs · method · engines │
                 │  labels · outputs · QA     │
                 └─────────────┬──────────────┘
                               │
                    validate (structural + optional semantic)
                               │
                               v
                 ┌────────────────────────────┐
                 │   Publish / package store  │
                 │   validated corpus         │
                 └─────────────┬──────────────┘
          ┌────────────────────┼────────────────────┐
          v                    v                    v
   Manager bot            Company bot          Downstream
   (team / role RAG)      (org-wide RAG,       consumers
                          scoped by policy)    (sourcing, audit)
          │                    │
          └──────────┬─────────┘
                     v
              Planner bot
         (corpus + gate signals →
          proposed Standard/profile changes)
                     │
                     v
              HITL approval
         (human owner accept/edit/reject
          Standard or profile changes)
                     │
                     v
              Updated Standard / profiles
              (versioned; agents must conform)
```

### Capability checklist (all required in the complete product unless marked backlog)

#### Core loop (C1-C9)

| # | Capability | Description |
|---|------------|-------------|
| C1 | **Standard** | Analysis Package ap contract, profiles, schemas, examples |
| C2 | **Gate / CI** | Validate packages before "published"; structural required; semantic designed |
| C3 | **Package store** | Durable storage of packages + metadata index for query |
| C4 | **Manager bot** | Role/team-scoped RAG Q&A over *that tenant's* validated packages |
| C5 | **Company bot** | Org-scoped Q&A with stricter policy; still single-tenant content |
| C6 | **Planner bot** | Meta-agent: gaps/conformance → **proposals** to change Standard/profiles |
| C7 | **HITL (Standard)** | Human approve/edit/reject Planner proposals before Standard goes live |
| C8 | **Agent runtime contract** | Planning agents read/write packages; same gate as CI |
| C9 | **Trust / tenancy** | Isolation, training eligibility, no cross-customer content pooling |

#### Load-bearing product capabilities (C10-C19) - required for complete product

| # | Capability | Description |
|---|------------|-------------|
| C10 | **Package-level human review** | Lead/reviewer workflow on a *package* (`qa.status`), not only on Standard changes |
| C11 | **AuthN / AuthZ** | Who can draft, publish, read (team vs company), HITL-approve, admin |
| C12 | **Package lifecycle** | Supersede, unpublish/recall, retention, legal hold |
| C13 | **Standard migration** | ap version upgrades; how old packages validate; compat policy |
| C14 | **PII / redaction before index** | Strip or flag secrets before bot indexing |
| C15 | **Eval harness** | Bot citation accuracy; gate false-positive metrics; regression packs |
| C16 | **Notify / webhooks** | Gate fail, HITL pending, publish, supersede → Slack/email/agent hooks |
| C17 | **Cycle diff** | Compare package vs prior cycle (manager/planner fuel) |
| C18 | **Gold / regression packs** | First-class reference packages for gate + engine replay |
| C19 | **Operator surface** | Minimal admin UI and/or CLI: search packs, HITL queue, gate dashboard |

#### Backlog (in scope as product may need later - not required for §18 complete)

| # | Capability | Description |
|---|------------|-------------|
| B1 | ERP/APS **connectors** (emit packs; do not replace Kinaxis/Anaplan) |
| B2 | Billing / entitlements (SaaS) |
| B3 | Multi-env (dev/stage/prod Standard pins) |
| B4 | Airgap / on-prem hardened install |
| B5 | Public docs site / multi-language SDKs |
| B6 | Collaboration (comments, @mentions on packs) |
| B7 | LLM cost caps / budget guards on bots |
| B8 | i18n of UI copy |

firstmate decides order and packaging. Hermes does not mandate phases.

---

## 4. Read order (context)

1. `docs/BRAND.md` + `brand/fathm-brand-final.html`  
2. `README.md`  
3. `docs/ARCHITECTURE.md`  
4. `standard/ap-0.2/STANDARD.md`  
5. `product/CI-L1.md`, `product/CI-L2.md`, `product/TRUST.md`  
6. `profiles/commodity_commit_forecast/README.md`  
7. `examples/commodity-commit-v1/`  
8. `docs/PITCH.md`  
9. `docs/DECISIONS.md`  
10. This file  

---

## 5. C1 - Analysis Package Standard

### Normative behavior
- Portable directory (YAML `MANIFEST.yaml` authoring; RO-Crate profile as canonical envelope target).  
- MUST metadata per `standard/ap-0.2/STANDARD.md`.  
- Labels: overrides / judgments / truths as jsonl (Web Annotation export optional).  
- Models draft only by default (D5); deterministic engines for math.  
- Profiles extend core (first: `commodity_commit_forecast`).  

### Build artifacts
- JSON Schema for manifest  
- Profile reason-code machine files  
- Example packages that remain golden  
- Optional: YAML → RO-Crate compiler  

### Acceptance
- Spec is machine-enforceable (schema + gate).  
- Example pack validates.  
- Second pack type *can* be added via profile without forking core (prove extensibility when you choose).

---

## 6. C2 - Gate / CI

### Structural (L1) - required capability
Stable check IDs (implement all that apply; add more if needed but keep IDs stable):

| ID | Intent |
|----|--------|
| `must_fields` | Schema validate MANIFEST |
| `standard_version` | Supported ap version |
| `layout_dirs` | Required dirs/files |
| `output_contract_files` | Contract paths exist |
| `inputs_pinned` | snapshot/hash or external_ref |
| `engines_pinned` | name, version, deterministic |
| `labels_paths` / `labels_jsonl_parse` | Label files exist and parse |
| `reason_codes_known` | Profile allow-list |
| `guideline_exists` | Method card present |
| `qa_status_enum` | Status enum |
| `training_eligibility_present` | Boolean present (default policy opt-in) |
| `no_unlabeled_diff` | Engine replay ⊆ overrides (when replay available) |

CLI sketch (names flexible if firstmate prefers, but keep a single shared entrypoint):

```bash
ap-gate check PATH [--json] [--html PATH]
```

Exit codes: 0 pass, 1 fail, 2 IO/usage.

### Semantic (L2) - required capability in complete product
LLM-assisted flags, e.g.:
- Narrative claims supported by outputs/labels  
- Judgments not presented as hard facts  
- Material overrides have evidence_refs  

Default policy recommendation: flag-not-block until calibrated - firstmate may choose otherwise with justification in docs.

### Acceptance
- Same gate library callable from CLI, CI, and agent tools.  
- No network required for pure L1.  
- Reports human-readable + JSON.

---

## 7. C3 - Package store

### Behavior
- Persist published packages (object store or git-backed or DB - firstmate choice).  
- Index metadata: package_id, as_of, profile, owners, qa.status, paths, tenant_id.  
- Query API: list/get/search by time range, profile, supplier/part fields if extracted.  
- Immutability: published versions content-addressed or versioned; edits → new package_version.

### Acceptance
- Given package_id, retrieve full package bytes + manifest.  
- List all packages for a tenant in a date range.  
- Gate status recorded with each publish.

---

## 8. C4 - Manager bot (team RAG)

### Behavior
- Answers questions **only** over validated packages in the caller's team/role scope.  
- Cites package_id + field/path/override ids (grounded answers).  
- Refuses or hedges when corpus lacks evidence.  
- Respects `confidentiality` and `training_eligibility` flags.  
- Single-tenant: never retrieves another customer's packages.

### Example prompts
- "What did we override on ACME BBU last cycle and why?"  
- "Which packages are still draft this week?"  
- "Summarize exceptions for PSU-50."  

### Acceptance
- Every answer includes citations to package ids (or explicit "not in corpus").  
- Access control enforced by team/role.  
- Eval set: N questions with expected package citations (firstmate defines N).

---

## 9. C5 - Company bot (org RAG)

### Behavior
- Org-wide (within tenant) Q&A and rollups for leadership.  
- Stricter aggregation: may hide row-level detail by policy.  
- Same citation and tenancy rules as manager bot.  
- Distinct system prompt / tool scope from manager bot - not merely a renamed manager bot unless policy is identical by design.

### Acceptance
- Separate policy config from manager bot.  
- Cannot bypass team ACL to dump another team's raw packs if policy forbids.  
- Rollup answers still cite underlying package ids where claims are factual.

---

## 10. C6 - Planner bot

### Behavior
- Consumes: gate failure histograms, waiver rates, missing reason codes, profile drift, repeated overrides, manager/company dead-end questions.  
- Produces: **proposals** only - never silent Standard mutation.  
- Proposal object (suggested shape):

```yaml
proposal_id: prop_...
created_at: ISO-8601
kind: standard_change | profile_change | reason_code_add | check_add
summary: string
diff:   # structured patch or RFC-style
rationale: string
evidence: [package_ids, gate_stats refs]
status: pending_hitl | approved | rejected | withdrawn
```

### Acceptance
- Proposals are persisted and listable.  
- No auto-merge to live Standard without HITL.  
- Dry-run: show which recent packages would newly pass/fail under proposal.

---

## 11. C7 - HITL approval

### Behavior
- Human owner(s) review Planner proposals.  
- Actions: approve / approve-with-edits / reject (reason required).  
- On approve: bump Standard or profile version; publish changelog; notify agents.  
- Audit log: who, when, before/after version.  
- Config: which roles are approvers (open item in pitch - implement pluggable ACL).

### Acceptance
- Cannot apply Standard change without recorded human action.  
- Version history recoverable.  
- Agents/gate pin `standard_version` / profile version and fail closed on unknown required versions if configured.

---

## 12. C8 - Agent runtime contract

Planning agents that pair with humans **must**:

1. Open/create package before mutating outputs  
2. Pin inputs and method  
3. Write overrides to labels  
4. Emit only output_contract paths  
5. Call the **same** gate before claiming final/published  
6. Not use chat memory as system of record after the turn  

Provide:
- Tool/API defs agents can call (`package.create`, `package.check`, `package.publish`, …)  
- Reference integration notes for OpenClaw/Claude/captain-style harnesses  

### Acceptance
- Documented tool schema.  
- At least one reference agent script or eval that produces a package and passes gate.

---

## 13. C9 - Trust, tenancy, training

**Decided (non-negotiable):**

- No cross-customer **content** training or pooling  
- Pooled learning only on structure/conformance telemetry if ever enabled  
- Team/company bots single-tenant  
- `training_eligibility` opt-in (default false)  
- Customer can export packages and leave  

See `product/TRUST.md`.

### Acceptance
- Architecture doc shows tenant boundary.  
- Tests or threat notes for cross-tenant isolation.  
- No default outbound ship of package bodies to third parties.

---

## 13a. C10 - Package-level human review

HITL on the **Standard** (C7) is not enough. Weekly packs need a human lead path.

### Behavior
- Package `qa.status`: `draft` → `in_review` → `approved` | `rejected` (align with standard enums).  
- Reviewer role distinct from analyst (may be same person only if policy allows).  
- Gate may be required before `in_review` or before `approved` (policy knobs).  
- Comments/reason on reject.  
- Approved package is what bots treat as "published corpus" by default (drafts excluded unless caller has elevate).

### Acceptance
- Cannot mark `approved` without recorded reviewer identity (or explicit self-approve policy flag).  
- Manager/company bots default to approved packages only.  
- Audit: who transitioned status when.

---

## 13b. C11 - AuthN / AuthZ

### Roles (minimum model - firstmate may rename)

| Role | Typical powers |
|------|----------------|
| `analyst` | create/edit draft packages, run gate, submit for review |
| `reviewer` | package approve/reject |
| `team_reader` | manager-bot + read team packages |
| `company_reader` | company-bot + org rollups per policy |
| `standard_approver` | HITL on Planner proposals (C7) |
| `admin` | tenant config, webhooks, retention, API keys |

### Behavior
- Every API call tenant-scoped.  
- Bots inherit caller's authz (no privilege escalation via prompt).  
- Service accounts for CI/agents with least privilege (publish vs read).

### Acceptance
- Matrix documented and enforced in tests (at least: reader cannot approve; other-tenant deny).  
- Agent tokens cannot call company bot beyond grant.

---

## 13c. C12 - Package lifecycle

### Behavior
- **Supersede:** new `package_version` or successor `package_id` links `replaces`.  
- **Unpublish / recall:** remove from default bot corpus; retain bytes for audit if policy requires.  
- **Retention:** configurable TTL or legal hold flag blocks delete.  
- **Export:** full package zip/crate for customer exit.

### Acceptance
- Superseded packs not cited as current by bots unless asked for history.  
- Recall is reversible only by admin + audit.  
- Legal hold prevents destructive delete.

---

## 13d. C13 - Standard migration

### Behavior
- Registry of supported `standard_version` + profile versions.  
- Compat policy per version: `validate`, `validate_with_warnings`, `reject`.  
- Migration notes / optional automated manifest upgraders when safe.  
- Gate and agents pin versions; unknown required version fails closed if configured.

### Acceptance
- Documented matrix for ap/0.2 → next.  
- Old packages remain retrievable.  
- CI can run gate under multiple standard versions.

---

## 13e. C14 - PII / redaction before index

### Behavior
- Indexing pipeline for bots runs **redaction stage**: API keys, emails, SSNs-like patterns, custom allow/deny field paths.  
- Redaction report stored on package (`qa/redaction.json` or store sidecar).  
- Fail or warn policy if high-severity secret detected in labels/outputs.  
- Raw package in store may remain complete for authorized humans; **bot index uses redacted view**.

### Acceptance
- Secret-like strings in fixture pack do not appear in bot retrieval chunks.  
- Analyst with permission can still open raw package.  
- Policy documented in TRUST.

---

## 13f. C15 - Eval harness

### Behavior
- **Gate evals:** fixture packs with expected pass/fail per check id; track false positives.  
- **Bot evals:** question → expected package_id citations; score recall/precision.  
- **Gold packs:** C18 packages used as regression anchors for engines/gate.  
- Run in CI on schedule or every PR affecting bots/gate.

### Acceptance
- `make eval` or `pytest` path documented.  
- Baseline scores recorded in repo (or CI artifact).  
- Regression fails the build when scores drop beyond threshold (threshold firstmate-set).

---

## 13g. C16 - Notify / webhooks

### Events (minimum)
- `package.gate.failed` / `package.gate.passed`  
- `package.review.requested` / `package.approved` / `package.rejected`  
- `package.published` / `package.superseded` / `package.recalled`  
- `proposal.created` / `proposal.decision`  
- `standard.version.released`

### Behavior
- Webhook endpoints with signed payloads (HMAC).  
- Optional email/Slack adapters.  
- No package **body** in webhook by default - ids + links + status only (trust).

### Acceptance
- Test consumer receives signed events.  
- Retry/backoff documented.  
- Payload schema versioned.

---

## 13h. C17 - Cycle diff

### Behavior
- Given package A and prior package B (same profile + lineage key e.g. commodity/team):  
  - manifest field diff  
  - output table diff (key rows)  
  - overrides added/removed  
- API + manager-bot tool: "what changed vs last cycle?"  
- Planner bot may consume diffs for proposal evidence.

### Acceptance
- Diff API returns structured result for example lineage.  
- Bot can answer a change question with citations to both package ids.

---

## 13i. C18 - Gold / regression packs

### Behavior
- Packages marked `gold: true` or stored under `examples/gold/` / tenant gold registry.  
- Gate `no_unlabeled_diff` / engine replay compares against gold when configured.  
- CI fails if gold pack stops passing gate after code change.

### Acceptance
- At least one gold pack in repo (commodity example may be promoted).  
- Document how to mint a new gold (reviewer + admin).

---

## 13j. C19 - Operator surface

### Behavior
Minimal **chart room** console and/or CLI:
- Search/list packages (filters: status, profile, as_of, team)  
- Open package detail + gate report  
- HITL queue (Standard proposals)  
- Package review queue  
- Gate dashboard (pass rate, top failing checks)  
- Brand: follow `brand/fathm-brand-system-v1.html` for any web UI  

CLI-only is acceptable for early complete if all actions exist; web UI preferred for design partner.

### Acceptance
- Operator can complete review + HITL without raw DB access.  
- Surfaces respect AuthZ (C11).

---

## 14. Suggested code layout (non-binding)

firstmate may reorganize freely. A coherent monorepo sketch:

```
analysis-package/           # existing GH repo
  standard/                 # ap schemas, profiles
  examples/                 # including gold/
  brand/                    # brand system
  src/ap_gate/              # validation library + CLI
  src/ap_store/             # package store + lifecycle + index
  src/ap_bots/              # manager, company, planner agents
  src/ap_hitl/              # Standard HITL + package review APIs
  src/ap_agent_tools/       # tool schemas for pair agents
  src/ap_auth/              # authn/z
  src/ap_redact/            # PII redaction for index
  src/ap_diff/              # cycle diff
  src/ap_notify/            # webhooks
  src/ap_eval/              # eval harness
  src/ap_ops/               # operator CLI/UI
  tests/
  docs/
```

Alternative: separate services - OK if interfaces stay clear and repo documents them.

---

## 15. Interfaces (minimum contracts)

Define and version these (OpenAPI/JSON Schema/whatever firstmate prefers):

| Interface | Consumer |
|-----------|----------|
| `POST /packages/validate` | CI, agents, UI |
| `POST /packages` (publish) | agents, humans |
| `POST /packages/{id}/review` | package HITL (C10) |
| `POST /packages/{id}/supersede` | lifecycle |
| `POST /packages/{id}/recall` | lifecycle |
| `GET /packages/{id}` | bots, UI |
| `GET /packages?query=` | bots, UI |
| `GET /packages/{id}/diff?prior=` | cycle diff |
| `POST /chat/manager` | manager bot |
| `POST /chat/company` | company bot |
| `GET/POST /proposals` | planner bot, Standard HITL |
| `POST /proposals/{id}/decision` | Standard HITL |
| `GET /standard/versions` | gate, agents |
| `POST /webhooks` / event deliver | notify |
| `POST /eval/run` or CI-only | eval harness |

Auth model: tenant-scoped (C11). Webhook payloads: ids/status by default, not full bodies.

---

## 16. Primary wedge vertical

**Profile:** `commodity_commit_forecast` (ops/finance-adjacent planning packs).  
Excel/agent UI allowed; package is the publish artifact.  
Design partner path: one real team producing packages under the Standard.

---

## 17. Quality and house rules

- Prefer simple, robust, maintainable over clever  
- No em dashes in prose (`-` instead)  
- No agent git co-author trailers  
- Bugs: reproduce E2E as user before fixing  
- Gate deterministic for structural checks  
- Brand: fathm product, ap format  

---

## 18. Definition of "complete product" (acceptance for full system)

A build is **complete** when all are true:

**Core loop**
1. **Standard** enforceable via schema + gate  
2. Packages **publish** only when gate policy says so  
3. **Store** holds versions and supports retrieval/search  
4. **Manager bot** answers with citations inside team scope  
5. **Company bot** answers with org policy and citations  
6. **Planner bot** emits proposals from corpus/gate evidence  
7. **Standard HITL** is mandatory path for live Standard/profile changes  
8. **Trust** boundaries tested/documented  
9. **Reference agent** can complete a cycle end-to-end  
10. Docs allow a new engineer to run the stack locally or on Pi  

**Load-bearing (C10-C19)**
11. **Package review** workflow works (draft → review → approved) with audit  
12. **AuthZ** enforced (role matrix + cross-tenant deny tests)  
13. **Lifecycle:** supersede + recall + retention/hold path exists  
14. **Standard migration** policy documented and gate supports multi-version validate  
15. **Redaction** prevents secrets in bot index fixtures  
16. **Eval harness** runs in CI with baseline  
17. **Webhooks** fire on publish/review/proposal events (signed)  
18. **Cycle diff** API (or CLI) works on example lineage  
19. **Gold pack** in CI regression  
20. **Operator surface** can review packs + HITL without DB poking  

Backlog B1-B8 is **not** required for this complete bar.

firstmate may ship partial increments; "done for full system" means 1-20 above.

---

## 19. Explicitly never / not required

**Never**
- Cross-customer shared **content** models  
- Chat transcript as system of record  
- Replacing ERP/APS as system of record  

**Not required for complete (backlog OK)**
- B1-B8 (connectors, billing, multi-env, airgap, public docs/SDK sprawl, collab comments, LLM cost caps, i18n)  
- Public fundraise materials  
- Final public domain/brand legal clearance  
- Perfect master data before packaging  

---

## 20. Open product decisions (firstmate may resolve or escalate to Tom)

- Who holds Standard HITL vs package reviewer roles in a customer org  
- Manager vs company bot policy matrix defaults  
- Semantic L2 block vs flag defaults  
- Store technology  
- Hosted SaaS vs on-prem/Pi-first for design partner  
- PyPI publish vs private install only  
- Webhook payload richness vs trust (default: ids only)  
- Self-approve packages allowed for tiny teams?  

---

## 21. Kickoff for firstmate

```bash
cd ~/firstmate/projects/fathm && git pull
# Read docs/DESIGN-FATHM-SYSTEM.md (this file)
# You own sequencing, architecture packaging, and sprint cuts.
# Deliver toward complete product acceptance §18 (items 1-20).
```

**Hermes responsibility:** standard draft, brand, research, example pack, this design.  
**firstmate responsibility:** build the system; choose phasing; PR quality; runtime on Pi/partner.

---

## 22. Related files

| File | Role |
|------|------|
| `docs/DESIGN-FATHM-MVP.md` | Earlier L1-only draft (superseded for scope; keep for historical checklists) |
| `docs/FIRSTMATE-KICKOFF.md` | Short card - update to point here |
| `docs/PITCH.md` | Narrative |
| `docs/ARCHITECTURE.md` | Diagram-level join |

**This document is the build authority for system scope.**
