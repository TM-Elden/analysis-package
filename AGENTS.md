# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Repo shape

Three things live here: **the Standard** (`standard/ap-0.2/` - normative Analysis Package contract,
JSON Schema, profiles), **the L1 gate** (`src/ap_gate/` - the `ap-gate` structural validator CLI/library),
and **phase-2 product** (`src/ap_store/`, `src/ap_review/`, `src/ap_auth/`, `src/ap_agent_tools/`,
`src/ap_api/` - package store, review workflow, authz scaffold, agent runtime slice, HTTP interface
layer; see "Phase 2" below). Brand is **fathm**; the portable format is **Analysis Package (ap)**; the
CLI/library name **ap-gate** stays format-neutral - never rename normative identifiers to "fathm X" in
code. See `docs/DESIGN-FATHM-SYSTEM.md` (build authority for full-system scope, section 20a for the
adopted phase sequencing) and `docs/DESIGN-FATHM-MVP.md` (superseded for scope, still authoritative for
L1 implementation detail).

## Build / test

```bash
pip install -e ".[dev]"
pytest -q
ap-gate check examples/commodity-commit-v1
PYTHONPATH=src python3 -m ap_api          # interface layer, http://127.0.0.1:8000
PYTHONPATH=src python3 -m ap_agent_tools.reference_agent --dest /tmp/demo-pack
```

No PyPI publish (git install only, per `docs/DECISIONS.md`-adjacent open-question defaults). This sandbox
has no `pip`; system `apt` packages `python3-yaml`, `python3-jsonschema`, `python3-pytest`,
`python3-fastapi`, `python3-uvicorn`, `python3-httpx` cover local dev without a venv
(`sudo apt-get install <pkg>` if missing) - `PYTHONPATH=src` is enough to run `ap-gate`, `ap-api`, or
`pytest` without an editable install. On a real (non-apt) machine / in CI, `pip install -e ".[dev]"`
pulls the same set from PyPI via `pyproject.toml`.

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
- Any check resolving a manifest-declared path must go through `resolve_contained`
  (`src/ap_gate/checks/pathsafe.py`), not `pkg / rel_path` directly - manifests are planner/agent-submitted
  and an uncontained join lets a crafted path (absolute, or `..` traversal) escape the package directory.
- `_apply_waivers` in `registry.py` runs before `qa_approved_implies_pass` (and again after), not just
  once at the end - the meta check reads prior outcomes, so a waived failure must already read as `pass`
  by the time it runs.

## Phase 2: package store, review workflow, authz scaffold, agent tools, interface layer

Implements C3/C8/C10/C11 and the section-15 interface table from `docs/DESIGN-FATHM-SYSTEM.md`
(section 20a: "Phase 2 - unchanged in content ... stays headless; its users remain engineers,
agents, and CI"). Every module below builds on `ap_gate` as a library (`CheckContext` + `run_all` +
`build_report`) - none of them re-implement gate logic; `ap-gate check`, `ap_store.publish`,
`ap_review`'s gate-before-review, and `ap_agent_tools.package_check` all call the exact same
functions.

- **Storage choice**: `src/ap_store/` is a content-addressed local filesystem blob store
  (deterministic gzip-tar per package directory, sharded by sha256 under `<root>/blobs/`) plus a
  SQLite metadata index (`<root>/index.sqlite3`) - no external DB service, per the phase-2 brief's
  "dependency-light" instruction. Single-tenant by design: no `tenant_id` anywhere in
  `ap_store/db.py`'s schema (packages already carry no `tenant_id` either, established in phase 1);
  if multi-tenancy is ever needed it is a store-level concept (one `PackageStore` root per tenant),
  not a column threaded through every query here.
- **Immutability model**: `(package_id, package_version)` is a primary key written once.
  Republishing identical bytes is a no-op (idempotent); republishing different bytes under the same
  pair raises `ImmutabilityError` - an edit must bump `package_version`. `status`, however, is a
  **mutable** column: it is `ap_review`'s live workflow state, deliberately decoupled from whatever
  `qa.status` the immutable manifest happened to declare at publish time. This mirrors the existing
  `qa.checks[]`-is-historical precedent above - the manifest snapshot is a point-in-time record, the
  store row is the live source of truth for review status. `PackageStore` uses one
  `sqlite3.connect(..., check_same_thread=False)` connection guarded by an internal `RLock` (not one
  connection per call) - `ap_api`'s FastAPI sync route handlers each run in their own threadpool
  worker thread, so the store must tolerate cross-thread use.
- **Review workflow** (`src/ap_review/`): `draft -> in_review -> approved | rejected`, plus two
  practical extensions beyond that literal set - `in_review -> draft` (withdraw) and
  `rejected -> draft` (revise/resubmit) - documented in `ap_review/workflow.py` as the judgment call
  they are; without them `rejected` is a dead end. Policy knobs live in `ap_review/policy.py`:
  `gate_before_review` (default `True` - re-runs the real gate against the package's immutable
  stored bytes before allowing `draft -> in_review`) and `allow_self_review` (default `False` -
  requires the deciding actor's id to differ from `owners.analyst.id`; `admin` bypasses both the
  role and self-review checks). `ReviewWorkflow` owns policy; `PackageStore.set_status` owns
  mechanism (compare-and-swap + audit row) - it enforces no policy itself.
- **Identity model** (`src/ap_auth/`): `Identity(id, roles: frozenset[Role])`, roles taken verbatim
  from the design doc's C11 minimum set. No login/session system exists yet (phase 3's job) - CLI
  callers self-identify via `AP_ACTOR_ID` / `AP_ACTOR_ROLES` env vars
  (`ap_auth.identity.identity_from_env`); HTTP callers via the `X-Ap-Actor-Id` / `X-Ap-Actor-Roles`
  headers (`ap_api/deps.py::identity_from_request`). **This is a documented placeholder, not
  authentication** - any caller can claim any identity by setting the header/env var. Phase 3 swaps
  the header source for a real session-derived identity; every downstream call site only ever sees
  the same `Identity` dataclass, so nothing else changes. Every state-changing action in `ap_store` /
  `ap_review` takes an `Identity` and records `id` + `roles` in `package_audit` - never a bare string.
- **Agent runtime slice** (`src/ap_agent_tools/`): `TOOL_SCHEMAS` documents `package.create` /
  `package.check` / `package.publish`; `package_check()` is a thin wrapper over the same
  `ap_gate.checks.registry.run_all` function everything else uses. `templates/commodity_commit_forecast/`
  is a copy of `examples/commodity-commit-v1`'s fixtures (not a second implementation) that
  `package_create()` scaffolds from, rewriting only identity/ownership/QA manifest fields.
  `reference_agent.py` runs create -> check -> publish end to end and is what
  `tests/test_agent_tools.py::test_reference_agent_produces_a_real_passing_published_package`
  exercises.
- **Interface layer** (`src/ap_api/`, FastAPI): `ap_api/app.py` implements the section-15 minimum
  (`POST /packages/validate`, `POST /packages`, `POST /packages/{id}/review`, `GET /packages/{id}`,
  `GET /packages`) plus `GET /packages/{id}/audit`. `package.publish` **is not a stub** - the store's
  publish semantics were ready, so C8's escape hatch didn't apply. Local-first scope note:
  `package_dir` fields are filesystem paths the *server* process reads, not uploads - no
  hosting/deployment model has been decided (design doc section 20, still open), so this stays
  Pi/local-first without foreclosing a later hosted deployment (which would add an upload step ahead
  of these endpoints, not change their shape). Sharp edge: `ap_api/deps.py::get_workflow` takes
  `store` as a `Depends(get_store)` **parameter**, not a direct `get_store()` call - a direct call
  bypasses `app.dependency_overrides[get_store]` entirely (FastAPI only rewires dependencies it
  resolves itself), which silently breaks tests that swap in a temp store. Sharp edge:
  `ap_api/__init__.py` deliberately does **not** re-export `app` from `ap_api.app` - `from
  ap_api.app import app` inside `__init__.py` shadows the `ap_api.app` *submodule* with the FastAPI
  *instance* (same name), breaking `import ap_api.app; ap_api.app.<anything>`; use `from
  ap_api.app import app` (or the `ap_api.app:app` module-path string uvicorn/the console script use)
  at the call site instead.

## Gold-pack regression

`examples/commodity-commit-v1` must always pass `ap-gate check`. `.github/workflows/ci.yml` and
`tests/test_example_passes.py` both enforce this - if you change a check or the example, run
`ap-gate check examples/commodity-commit-v1` before committing.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
