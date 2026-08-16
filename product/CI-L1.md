# L1 CI - Structural gate

## Purpose

Block or flag publish when an Analysis Package fails machine-checkable completeness. No LLM required.

## Checks (v1 - canonicalized)

> These IDs are the single source of truth: `src/ap_gate/checks/registry.py`. This table previously
> disagreed with both `docs/DESIGN-FATHM-MVP.md` and `docs/DESIGN-FATHM-SYSTEM.md` (three different ID
> sets across the three documents). It is now reconciled to `docs/DESIGN-FATHM-SYSTEM.md`'s canonical
> set plus `qa_approved_implies_pass` (the one useful MVP-only addition) - see the phase-1 build report
> for the full reasoning. IDs are the vocabulary any future gate-failure telemetry or conformance
> histogram would key off of; do not rename one without a strong reason, and never reuse a retired ID
> for a different meaning.

| Check ID | Severity | Pass condition |
|----------|----------|----------------|
| `must_fields` | required | MANIFEST.yaml satisfies the ap/0.2 MUST-field JSON Schema |
| `standard_version` | required | `standard_version` is in the supported set (data-driven, `src/ap_gate/versions.py`) |
| `layout_dirs` | required | Required package directories exist (`inputs/` unless all-external_ref, `outputs/`, `labels/`, `qa/`) |
| `guideline_exists` | required | `GUIDELINE.md` at package root, or `method.guideline_path` exists |
| `output_contract_files` | required | Every `output_contract[].path` exists and is non-empty |
| `inputs_pinned` | required | Each input has an existing `path` (hash-verified if `content_sha256` set) or a valid `external_ref` block |
| `engines_pinned` | required | Every engine has `name`, `version`, `deterministic`; if `path` is set, that file exists |
| `labels_paths` | required | `labels.overrides_path` / `judgments_path` / `truths_applied_path` all point to existing files (may be empty) |
| `labels_jsonl_parse` | required | Every non-empty line in each label file parses as a JSON object |
| `reason_codes_known` | required | Every override's `reason_code` is in the profile's allow-list (`profiles/<name>/reason_codes.json`); `OTHER` requires `reason_text`. Skips if the profile has no registered allow-list. |
| `qa_status_enum` | required | `qa.status` is one of `draft` / `in_review` / `approved` / `rejected` |
| `training_eligibility_present` | required | `training_eligibility` is present and boolean |
| `qa_approved_implies_pass` | required | If `qa.status == approved`, no other required check (except `no_unlabeled_diff`) failed. Evaluates the gate's own freshly computed results, never the manifest's `qa.checks[]` historical record. Skips when status isn't `approved`. |
| `no_unlabeled_diff` | required | **Stubbed - always `skip`.** Engine replay (output delta vs. `labels/overrides.jsonl`) needs real deterministic engine implementations; phase 2 (see `AGENTS.md`) didn't add these, so this stays future work with no phase assigned yet. |

Waivers: `qa.waivers[]` entries `{check_id, reason, author}` turn a failing check into `result: pass, waived: true`. Waiver `author` is never surfaced in gate output (report evidence or results) - see the report shape below.

Path safety: `inputs_pinned`, `engines_pinned`, `labels_paths`, `guideline_exists`, and `output_contract_files` resolve every manifest-declared path under the package directory only; a path that escapes it (absolute, or `..` traversal) fails that check rather than being followed.

## Report shape (layered)

The gate's JSON report separates a content-free layer from a human-facing one, by design, not as an
afterthought - this is what lets a future conformance-telemetry pipeline consume `results[]` directly
without parsing or scrubbing free text, and it is what keeps gate statistics package-level rather than
person-level:

- `results[]`: `{check_id, result, severity, waived}` only. No paths, no values, no messages, no person
  identifiers (`author`, `owners.*`).
- `evidence[]`: `{check_id, message, paths}`. Human-facing - written to tell the planner which path, which
  field, and how to fix it. Also never carries person identifiers.

## CLI

```bash
ap-gate check path/to/package
ap-gate check path/to/package --json
ap-gate check path/to/package --html report.html
```

Exit codes: `0` pass (including waived), `1` fail, `2` IO/usage error. Agents MUST use the same
entrypoint (D6C) - there is no second soft path.

## Not in L1

- "Does the prose conclusion follow from the data?" -> L2
- Model quality of free-text reason_text
- Full cryptographic supply chain of ERP extracts beyond declared hashes
- Real engine implementations / `no_unlabeled_diff` engine replay (future work, not yet phase-scheduled)

## Pilot success metrics

- % packages reaching publish with gate pass
- Flag rate trend over 4-6 weeks
- % published packages with complete queryable provenance fields (target 100%)
