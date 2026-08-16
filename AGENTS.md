# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Repo shape

Two joint things live here: **the Standard** (`standard/ap-0.2/` - normative Analysis Package contract,
JSON Schema, profiles) and **the product** (`src/ap_gate/` - the `ap-gate` L1 structural validator CLI).
Brand is **fathm**; the portable format is **Analysis Package (ap)**; the CLI/library name **ap-gate**
stays format-neutral - never rename normative identifiers to "fathm X" in code. See `docs/DESIGN-FATHM-SYSTEM.md`
(build authority for full-system scope) and `docs/DESIGN-FATHM-MVP.md` (superseded for scope, still
authoritative for L1 implementation detail).

## Build / test

```bash
pip install -e ".[dev]"
pytest -q
ap-gate check examples/commodity-commit-v1
```

No PyPI publish (git install only, per `docs/DECISIONS.md`-adjacent open-question defaults). This sandbox
has no `pip`; system `apt` packages `python3-yaml`, `python3-jsonschema`, `python3-pytest` cover local dev
without a venv (`sudo apt-get install python3-pytest` if missing) - `PYTHONPATH=src` is enough to run
`ap-gate` or `pytest` without an editable install.

## `ap-gate` architecture

- `src/ap_gate/checks/registry.py` holds the **canonical check-ID list** - the single source of truth,
  also mirrored in `product/CI-L1.md`. Check IDs are long-lived vocabulary (future conformance
  telemetry keys off them); don't rename one without strong reason, and never reuse a retired ID.
- `src/ap_gate/versions.py` is the only place standard_version -> schema-file mappings live (data-driven,
  not literals scattered through checks). `src/ap_gate/load_manifest.py` is the only place that touches
  YAML - keeps a future alternate envelope loader (RO-Crate) a swap in one module.
- The gate's JSON report is **layered by design**: `results[]` is content-free
  (`{check_id, result, severity, waived}`, no paths/values/messages/person-identifiers) for future
  telemetry; `evidence[]` is the human-facing layer (planner-serving messages: which path, which field,
  how to fix). Never let a check's `message`/`paths` leak into `results[]`, and never put `author` or
  `owners.*` into either layer.
- `standard/ap-0.2/schemas/manifest.schema.json` is open-world by design: no `additionalProperties: false`
  anywhere. Profile-specific requirements (reason-code allow-lists, etc.) live in
  `profiles/<name>/*.json` machine files, loaded by `src/ap_gate/profiles.py` - never forked into this
  schema.
- `no_unlabeled_diff` is permanently stubbed (always `skip`) until real deterministic engines exist for
  `examples/commodity-commit-v1` to replay against - that's a phase-2 candidate, not a bug.
- The manifest's `qa.checks[]` is a historical record the package carries, separate from what the gate
  computes fresh each run (`qa_approved_implies_pass` evaluates the gate's own results, never `qa.checks[]`).

## Gold-pack regression

`examples/commodity-commit-v1` must always pass `ap-gate check`. `.github/workflows/ci.yml` and
`tests/test_example_passes.py` both enforce this - if you change a check or the example, run
`ap-gate check examples/commodity-commit-v1` before committing.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
