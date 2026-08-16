# Changelog

## Unreleased - phase 2: package store, review workflow, authz scaffold, agent tools, interface layer

Implements C3/C8/C10/C11 and the section-15 interface table from `docs/DESIGN-FATHM-SYSTEM.md`
(section 20a). Stays headless - engineers, agents, and CI only, no UI. Full architecture notes live in
`AGENTS.md`'s "Phase 2" section; not repeated here.

- New: `src/ap_store/` - content-addressed local filesystem blob store + SQLite metadata index (C3).
  Publish is immutable per `(package_id, package_version)`; `status` is a separate mutable column
  seeded to `draft` on publish, decoupled from the manifest's own `qa.status`.
- New: `src/ap_review/` - `draft -> in_review -> approved | rejected` review workflow (C10), plus
  `in_review -> draft` and `rejected -> draft`. Policy knobs: `gate_before_review` (default on),
  `allow_self_review` (default off).
- New: `src/ap_auth/` - `Identity`/`Role` data model (C11 minimum role set). CLI callers via
  `AP_ACTOR_ID`/`AP_ACTOR_ROLES` env vars, HTTP callers via `X-Ap-Actor-*` headers - both documented
  placeholders, not authentication.
- New: `src/ap_agent_tools/` - `TOOL_SCHEMAS` for `package.create`/`package.check`/`package.publish`
  (C8) and a `reference_agent.py` that runs create -> check -> publish end to end against a
  `commodity_commit_forecast` template copied from `examples/commodity-commit-v1`.
- New: `src/ap_api/` (FastAPI) - `POST /packages/validate`, `POST /packages`,
  `POST /packages/{id}/review`, `GET /packages/{id}`, `GET /packages`, `GET /packages/{id}/audit`.
- 49 new tests covering store round-trip/immutability, the review state machine, and identity/audit
  trail on state transitions. `examples/commodity-commit-v1` still passes `ap-gate check` unchanged.

## Unreleased - phase 1: Standard schema + `ap-gate` L1 structural validator

**Standard (`standard/ap-0.2/`)**
- Editorial reconciliation pass on `STANDARD.md` (v0.2.1, no MUST field removed or narrowed): added
  `profile` to the MUST table; renamed the `profile: strict` extensibility switch to
  `validation_mode: strict` (it collided with the `profile` field); adopted `labels.overrides_path` /
  `judgments_path` / `truths_applied_path` naming; split `training_eligibility` (MUST, bool) from
  `training_eligibility_reason` (SHOULD, string); clarified `qa.checks[]` is MUST only from `in_review`
  onward; clarified `owners.agent` is a required-but-nullable field; clarified `confidentiality` is a
  free-form string in v0; added `path` to `output_contract` entries and clarified `outputs[]` is a
  non-authoritative convenience mirror. Fixed broken `meta/...` related-file links to the paths that
  actually exist in this repo (`research/`). Full itemized list in `STANDARD.md`'s own changelog section.
- Reconciled `manifest.example.yaml` to the amended Standard (added `standard_version`/`profile`, fixed
  `training_eligibility` default, renamed `four_bucket_map.structured_inputs` to `structured`, dropped
  the undocumented `qa.consensus` field).
- New: `standard/ap-0.2/schemas/manifest.schema.json` - JSON Schema (draft 2020-12) for the MUST-field
  list. Open-world by design: no `additionalProperties: false` on the manifest root or any extensible
  object, so profiles can extend without forking this schema.
- New: `profiles/commodity_commit_forecast/reason_codes.json` - machine-readable reason-code allow-list
  for the `reason_codes_known` check, replacing hand-maintained prose as the source of truth.

**`ap-gate` CLI (`src/ap_gate/`)**
- New: `ap-gate check PATH [--json] [--html PATH]`. Same entrypoint for CLI, CI, and future agent tooling.
- Canonicalized the check-ID registry (`src/ap_gate/checks/registry.py`), resolving a three-way ID
  divergence across `product/CI-L1.md`, `docs/DESIGN-FATHM-MVP.md`, and `docs/DESIGN-FATHM-SYSTEM.md` in
  favor of the system doc's set, plus `qa_approved_implies_pass` (the one useful MVP-only addition).
  `product/CI-L1.md` updated to match.
- `engines_pinned` now additionally verifies `engines[].path` exists on disk when set (previously a
  dangling path passed silently).
- Every check that resolves a manifest-declared path (`inputs_pinned`, `engines_pinned`, `labels_paths`,
  `guideline_exists`, `output_contract_files`) goes through a shared containment check
  (`src/ap_gate/checks/pathsafe.py`): a path that escapes the package directory (`..` traversal or an
  absolute path) fails that check instead of being silently followed.
- `no_unlabeled_diff` is explicitly stubbed - always returns `skip`. Real engine implementations are a
  phase-2 candidate.
- Gate JSON report is layered: a content-free `results[]` (`{check_id, result, severity, waived}`) that
  never carries paths, values, messages, or person identifiers (`author`, `owners.*`), separate from a
  human-facing `evidence[]` layer written to tell the planner which path, which field, and how to fix it.
- Version and schema-path handling is a single data table (`src/ap_gate/versions.py`), not literals
  scattered through checks. Manifest loading is isolated in `src/ap_gate/load_manifest.py`.
- No tenant field anywhere in the manifest schema or gate - tenancy stays a store/deployment concern.

**Example package (`examples/commodity-commit-v1/`)**
- Fixed `outputs/exceptions.csv`: header/data mismatch (`severity` column actually held supplier names;
  renamed to `supplier` to match the output schema and the real data).
- Recomputed the five `content_sha256` values in `MANIFEST.yaml` against the actual bytes of the files
  under `inputs/` (previously placeholder `sha256:aaaa...`/`sha256:bbbb...` strings).
- Corrected false QA claims: `qa.checks[].inputs_hashed` now reflects the real (now-matching) hashes;
  `no_unlabeled_diff` corrected from a false `pass` to `skip`, matching its stubbed status.
- Dropped `engines[].path` for `bom_explode` / `allocate_suppliers` / `net_inventory` - those files don't
  exist yet (domain math, out of phase-1 scope; a phase-2 candidate). `engines_pinned` would otherwise
  fail on the dangling paths.
- Regenerated `qa/checks.json` as real `ap-gate check . --json` output, replacing the hand-authored file.
- The package now honestly passes `ap-gate check examples/commodity-commit-v1` end to end.

**CI**
- New: `.github/workflows/ci.yml` - installs `ap-gate`, runs the test suite, and runs
  `ap-gate check examples/commodity-commit-v1` as a gold-pack regression. Fails the build if the example
  stops passing the gate.

**Docs**
- `product/CI-L1.md` rewritten to the canonicalized check IDs and the layered report shape.
- Root `README.md`: added install + CLI quickstart, checked off the schema/CLI roadmap items.
