# commodity_commit_forecast package template (ap/0.2)

**Used by:** `ap_agent_tools.tools.package_create` (C8 agent runtime contract slice).

This is a copy of `examples/commodity-commit-v1`'s fixtures (inputs, deterministic engine stub,
labels, outputs, GUIDELINE) kept as a ready-to-scaffold template rather than a second implementation
- `package_create()` copies this directory tree, then overwrites only the identity/ownership/QA
fields in `MANIFEST.yaml` (`package_id`, `package_version`, `title`, `created_at`, `as_of`, `owners`,
`qa.status: draft`). Everything else - `output_contract`, `inputs[]` (including `content_sha256`,
still valid since the underlying files are unchanged), `method`, `engines`, `labels` paths - is
inherited as-is, since it still accurately describes the copied files.

No real domain engines exist yet (`bom_explode` / `allocate_suppliers` / `net_inventory` are pinned
by name/version but not implemented - see the parent example's own note and CLAUDE.md); a package
scaffolded from this template demonstrates the *contract* end to end (create -> check -> publish),
not a real computed forecast. Quantities are synthetic demo data inherited from the fixture, not live
production data.

## Tree

```
MANIFEST.yaml          # rewritten by package_create(); see above for which fields
GUIDELINE.md           # versioned method card
inputs/                # pinned snapshots (content_sha256 verified by ap-gate)
code/                  # deterministic entrypoint stub
outputs/               # forecast + exceptions + summary (fixture data)
labels/                # overrides, judgments, truths (jsonl)
qa/checks.json         # inherited from the fixture; package_create resets manifest qa.status to draft
```
