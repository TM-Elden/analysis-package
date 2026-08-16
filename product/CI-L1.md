# L1 CI - Structural gate

## Purpose

Block or flag publish when an Analysis Package fails machine-checkable completeness. No LLM required.

## Checks (v0)

| Check ID | Pass condition |
|----------|----------------|
| `must_fields` | MANIFEST contains all ap/0.2 MUST fields with valid types |
| `standard_version` | `standard_version` is supported |
| `output_contract_files` | Every output_contract path exists and is non-empty |
| `inputs_pinned` | Each input has snapshot_id+hash or valid external_ref block |
| `engines_pinned` | Every engine has name, version, deterministic bool |
| `labels_paths` | overrides/judgments/truths paths exist (may be empty files) |
| `no_unlabeled_diff` | When engine replay available: output delta ⊆ overrides.jsonl |
| `reason_codes_known` | All override reason_codes ∈ profile allow-list |
| `qa_status_consistent` | approved implies all required checks pass or waived with reason |

## CLI (planned)

```bash
ap-gate check path/to/package
ap-gate check path/to/package --json
```

Exit code non-zero on failure. Agents MUST use the same entrypoint (D6C).

## Not in L1

- "Does the prose conclusion follow from the data?" → L2  
- Model quality of free-text reason_text  
- Full cryptographic supply chain of ERP extracts beyond declared hashes  

## Pilot success metrics

- % packages reaching publish with gate pass  
- Flag rate trend over 4-6 weeks  
- % published packages with complete queryable provenance fields (target 100%)  
