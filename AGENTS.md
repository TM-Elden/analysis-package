# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Repo shape

Four things live here: **the Standard** (`standard/ap-0.2/` - normative Analysis Package contract,
JSON Schema, profiles), **the L1 gate** (`src/ap_gate/` - the `ap-gate` structural validator CLI/library),
**phase-2 product** (`src/ap_store/`, `src/ap_review/`, `src/ap_auth/`, `src/ap_agent_tools/`,
`src/ap_api/`, `src/ap_mcp/` - package store, review workflow, authz scaffold, agent runtime slice, HTTP
interface layer, agent-capture MCP server; see "Phase 2" below), and **phase-3-in-progress**
(`src/ap_redact/`, `src/ap_index/`, `src/ap_manager_bot/` - redaction pipeline, FTS5 search index, and
the C4 manager-bot backend; `src/ap_console/` - the server-rendered manager console; `src/ap_chat/` -
the planner-chat-v0 bot (Telegram adapter in `ap_chat/telegram/`); see "Phase 3" below), and
**phase-4-in-progress** (`src/ap_proposals/` - C6/C7 Standard-change proposal storage and workflow;
see "Phase 4" below). Brand is
**fathm**; the CLI/library name **ap-gate** stays format-neutral - never rename
normative identifiers to "fathm X" in
code. See `docs/DESIGN-FATHM-SYSTEM.md` (build authority for full-system scope, section 20a for the
adopted phase sequencing) and `docs/DESIGN-FATHM-MVP.md` (superseded for scope, still authoritative for
L1 implementation detail). `docs/` holds technical/design docs only; brand and pitch material lives in
`brand/` (`brand/BRAND.md`, `brand/PITCH.md`, `brand/PITCH-YC.md`, decks, and `brand/research/` for
naming/trademark research); `research/` holds only genuine research (findings, landscape, standards
foundation) - keep new marketing/brand material in `brand/`, not `docs/` or `research/`.

## Build / test

```bash
pip install -e ".[dev]"
pytest -q
ap-gate check examples/commodity-commit-v1
PYTHONPATH=src python3 -m ap_api          # interface layer, http://127.0.0.1:8000
PYTHONPATH=src python3 -m ap_agent_tools.reference_agent --dest /tmp/demo-pack
PYTHONPATH=src python3 -m ap_mcp.server   # fathm-ap MCP server, stdio JSON-RPC
```

No PyPI publish (git install only, per `docs/DECISIONS.md`-adjacent open-question defaults). This sandbox
has no `pip`; system `apt` packages `python3-yaml`, `python3-jsonschema`, `python3-pytest`,
`python3-fastapi`, `python3-uvicorn`, `python3-httpx`, `python3-jinja2`, `python3-python-multipart`
(the last needed by `ap_console`'s `Form()`-based routes, e.g. the review-queue actions) cover local
dev without a venv (`sudo apt-get install <pkg>` if missing) - `PYTHONPATH=src` is enough to run
`ap-gate`, `ap-api`, or `pytest` without an editable install. On a real (non-apt) machine / in CI,
`pip install -e ".[dev]"` pulls the same set from PyPI via `pyproject.toml` (which lists
`python-multipart` explicitly since FastAPI treats it as an optional soft-dependency it won't pull in
transitively).

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
  `examples/commodity-commit-v1` to replay against - phase 2 (see below) didn't touch this, it's
  future work with no phase assigned yet, not a bug.
- The manifest's `qa.checks[]` is a historical record the package carries, separate from what the gate
  computes fresh each run (`qa_approved_implies_pass` evaluates the gate's own results, never `qa.checks[]`).
- Any check resolving a manifest-declared path must go through `resolve_contained`
  (`src/ap_gate/checks/pathsafe.py`), not `pkg / rel_path` directly - manifests are planner/agent-submitted
  and an uncontained join lets a crafted path (absolute, or `..` traversal) escape the package directory.
- `_apply_waivers` in `registry.py` runs before `qa_approved_implies_pass` (and again after), not just
  once at the end - the meta check reads prior outcomes, so a waived failure must already read as `pass`
  by the time it runs.
- Severity has two values (`src/ap_gate/checks/types.py`): `required` (default; a `fail` blocks
  `overall`) and `advisory` (a `fail` surfaces in the report/CLI but never blocks - see
  `CheckOutcome.blocks_overall_pass`). Build an advisory outcome with `CheckOutcome.advisory_fail(...)`,
  not `fail(...)` plus a manual severity override. Today `agent_draft_present` is the only advisory
  check; a profile's `training_grade.json` opt-in can escalate it to `required` per tenant.
- Training-export additions (P1-P4, STANDARD.md v0.2.2, `standard/ap-0.2/schemas/override-row.schema.json`):
  a normative shape for every `labels/overrides.jsonl` row (`labels_row_shape` check), a per-profile
  `field_path_grammar.json` + `src/ap_gate/field_path.py` resolver (declarative only, not wired into
  any check), an optional `evidence_refs` `#rows=col:val` fragment (`src/ap_gate/evidence_refs.py`,
  SHOULD only, unenforced), and an optional `agent_draft` sub-object flagged by `agent_draft_present`.
  All four read a profile's `profiles/<name>/training_grade.json` (`ap_gate.profiles.load_profile_training_grade`)
  for opt-in escalation - core stays permissive; absence of the file means not opted in, same pattern
  as `reason_codes.json`'s "no file -> skip" precedent.

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
  from the design doc's C11 minimum set. CLI/library callers self-identify via `AP_ACTOR_ID` /
  `AP_ACTOR_ROLES` env vars (`ap_auth.identity.identity_from_env`) - this stays for same-machine
  tooling that never crosses a trust boundary. HTTP callers authenticate for real (the old
  `X-Ap-Actor-Id` / `X-Ap-Actor-Roles` header placeholder is gone, not left as a fallback): every
  downstream call site only ever sees the same `Identity` dataclass, exactly as phase 2 set up for
  this swap. Every state-changing action in `ap_store` / `ap_review` takes an `Identity` and records
  `id` + `roles` in `package_audit` - never a bare string.
- **C11 auth model** (`src/ap_auth/store.py`, `src/ap_auth/db.py`, `src/ap_auth/cli.py`): a sibling
  `auth.sqlite3` (own connect/lock pattern mirroring `ap_store.PackageStore`; kept separate from the
  package index deliberately - a leaked credentials DB and a leaked package index are different
  incidents) holds `users` (scrypt password hash via stdlib `hashlib.scrypt` - zero new
  dependencies, see `ap_auth/passwords.py`) and `sessions` (used for both browser sessions and
  service-account bearer tokens - same table shape, same validation path, `kind` column is
  informational only). No admin UI exists yet, so `ap-auth adduser/passwd/disable/enable/token/list`
  (`src/ap_auth/cli.py`) is the only provisioning path; it resolves the same default DB location
  (`$AP_AUTH_DB`, else `~/.fathm/auth.sqlite3`) `ap_api` does, so a newly-adduser'd user is
  immediately visible to a running server. `POST /login` (`ap_api/auth_routes.py`) verifies the
  password and sets an HttpOnly/SameSite=Lax/**Secure** session cookie plus returns a `csrf_token`
  the client must echo as `X-Csrf` on every state-changing request thereafter (derived from the
  session token itself via `ap_auth.csrf.csrf_token_for` - no server-side CSRF storage needed, since
  the HttpOnly cookie means no page script can compute a forged match). `POST /logout` revokes the
  session row. Service accounts (agents/CI) send `Authorization: Bearer <token>` instead and are
  exempt from the CSRF check (browsers never attach that header automatically, so there's no
  ambient-authority risk to defend against). `ap_api/deps.py::identity_from_request` is the single
  resolution point (bearer checked first, then cookie); `ap_api/deps.py::require_any_role` is the
  route-level role-matrix gate (e.g. `POST /packages` requires `analyst`) - `ReviewWorkflow` still
  owns the rest of the matrix (analyst-only submit, reviewer-only decide, distinct-reviewer policy).
  No JWTs, deliberately: server-side sessions are trivially revocable and there's exactly one
  server. Sharp edge for tests: a `Secure` cookie is only stored/replayed by httpx's cookie jar over
  an `https://` origin, so `TestClient(app, base_url="https://testserver")` is required (plain
  `TestClient(app)` silently drops the session cookie) - see `tests/test_api.py`.
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

## Phase 3 (in progress): C14 redaction, C4 retrieval index, C4 manager bot

Implements the redaction-before-index, search-index, manager-bot-backend, planner-chat, and
console-query-panel slices of §20a's adopted Phase 3 (`data/fathm-phase3-readiness/report.md`
sections 5.1/5.3/5.4/6 in the firstmate repo hold the full rationale). Manager console (below) and
planner chat (`src/ap_chat/`, below) are both consumers of `POST /chat/manager`.

- **`src/ap_redact/`** (C14): `redact.redact_package(package_dir, manifest, package_id=, package_version=)`
  is the pipeline entry point - `package dir -> (list[Chunk], RedactionReport)`. Person identifiers
  (`author` on every `labels/*.jsonl` row; `owners.analyst.id` / `owners.reviewer.id` /
  `owners.agent.*` in the manifest) are scrubbed by default (`ap_redact/field_paths.py`
  `DEFAULT_SCRUB_FIELD_PATHS`), both from the structured field they live in *and* from free-text
  mentions elsewhere (e.g. `RUN_SUMMARY.md` prose) via a second literal-value replacement pass in
  `redact.py::_scrub_mentions` - a field-path scrub alone only catches the field, not a value
  re-typed into prose. Business content (supplier names, part numbers, contract refs) is never
  touched - that's the corpus, not PII; `confidentiality` rides along as `Chunk` metadata for
  role-based filtering, never as a content edit. `secrets_scan.py` runs a regex detector set (AWS,
  GitHub, PEM headers, JWT-shaped, emails, SSN-like) plus a Shannon-entropy check over every text
  file in the package tree; any hit is `severity="high"` and fails the whole package closed - the
  returned chunk list is empty and `RedactionReport.blocked=True`. The entropy detector excludes
  pure-hex tokens (a package is full of legitimate `content_sha256` hashes) and uses a
  4.6-bits/char threshold tuned against this repo's own `contracts://...` `external_ref` style
  business content (~4.3) vs. real random secrets (~4.7-5.0) - see the threshold comment in
  `secrets_scan.py` before changing it. Per-profile `profiles/<name>/redaction.json`
  (`allow_field_paths` / `deny_field_paths` / `disabled_detectors`, loaded by
  `ap_gate.profiles.load_profile_redaction` - same "no file -> core defaults" pattern as
  `reason_codes.json`) is the tuning valve for both what gets scrubbed and false-positive secret
  hits. The `RedactionReport` is a **store sidecar**, never package content: `report.py`'s
  `write_report`/`read_report` persist it at `<store_root>/redaction/<package_id>/<package_version>.json`,
  outside the package's own immutable bytes and outside `qa/`.
- **`src/ap_index/`** (C4 retrieval layer): SQLite **FTS5** only, no vector DB/embeddings (report
  5.3: the entire pilot corpus is on the order of 10^4 tokens/year - see `ap_index/db.py`'s
  `UNINDEXED` tag columns for how BM25 full-text and structured-filter search share one table).
  `IndexStore` (`index_store.py`) consumes **only** `ap_redact.Chunk` objects - never a package
  path or manifest - so nothing unredacted can structurally reach the index. `index_package`
  replace-on-writes a whole package version's chunks (delete-then-insert on
  `(package_id, package_version)`); there is no partial/incremental update, by design, since a
  full package re-index is sub-second at this scale. `search(query, filters)` sanitizes free text
  through `_sanitize_fts_query` (every token literal-quoted) before handing it to FTS5's `MATCH` -
  raw fathm queries are full of `-`-bearing part numbers (`BBU-100`) that bare FTS5 syntax
  misparses as `NOT`. `reindex.py::reindex_package(store=, index=, store_root=, package_id=,
  package_version=)` is the reindex-on-status-change hook: it re-derives index membership from the
  store's *current* status on every call (`approved` -> redact + index; anything else -> ensure
  removed) rather than diffing a transition - this is a plain function a caller invokes after an
  `ap_review.ReviewWorkflow.transition(...)`, **not** wired as an automatic side effect of that
  call, to keep `ap_review` from gaining an `ap_index` import (see `ap_review`'s policy/mechanism
  split above - same layering discipline).
- **`src/ap_console/`** (P3.4, manager console shell): server-rendered Jinja2 + one vendored htmx
  file (`ap_console/static/htmx.min.js`) - no SPA, no node toolchain, per the phase-3 report's
  §5.1 rationale (`data/fathm-phase3-readiness/report.md` in the firstmate repo). **Module
  boundary**: `ap_console` renders HTML; `ap_api` stays the format-neutral JSON layer - `ap_console`
  reads straight from `PackageStore`/`ap_gate` (the same objects `ap_api.app` uses), it does not
  make HTTP calls back into `ap_api`'s own routes. The two exceptions are `POST /login` and
  `POST /logout` (owned by `ap_api.auth_routes`, at the root path, not under `/console`) - the
  console's login page posts to `/login` directly via `fetch`, and its logout button is an
  htmx-driven `POST /logout` with an `X-Csrf` header computed server-side on every page render
  (`ap_console/deps.py::console_csrf_token`, since the session cookie is HttpOnly and JS can't read
  it - see `ap_auth/csrf.py`). `include_console(app)` (`ap_console/routes.py`) is the single mount
  point `ap_api/app.py` calls - routes, the vendored static file, and an exception handler for
  `ConsoleAuthRequired` that redirects logged-out browser requests to `/console/login` (distinct
  from `ap_api.deps.identity_from_request`, which 401s JSON API callers instead - a console page
  needs the redirect, an API client needs the status code). The rendered gate report reuses
  `ap_gate.report.html_report.to_html` unchanged (`ap_console/gate_report.py` extracts the
  package's stored bytes to a scratch dir and re-runs the gate, mirroring what
  `ap_api.app._run_gate` does for `POST /packages/validate`) - never reimplement gate-report
  rendering here. List filtering (status/profile/date/title) is one htmx partial
  (`GET /console/packages/table`, `templates/_packages_table.html`) shared between the initial
  full-page render and swap-in-place updates - keep list columns in that one template, not
  duplicated between the full and partial views.
- **Console query panel** (P3.7, report §6): `GET /chat/manager/stream` (`ap_api/chat_routes.py`,
  root-mounted alongside `POST /chat/manager`, not under `/console` - same module-boundary reasoning
  as `/login`/`/logout` above) is the same `ManagerBot` behind an SSE `StreamingResponse`, consumed
  by `ap_console`'s `GET /console/chat` page (`templates/chat.html` + `_chat_turn.html`) via htmx's
  vendored `sse` extension (`ap_console/static/sse.js`, same 1.9.12 pin as `htmx.min.js`). It is
  `GET`, not `POST`: the browser's native `EventSource` can't send a body or custom headers, so the
  question travels as a query param and auth as the session cookie - GET being a safe method also
  means `identity_from_request` doesn't require the `X-Csrf` header the POST route does (see
  `ap_api/deps.py::_UNSAFE_METHODS`). **This is response-chunking, not model-level token streaming**:
  `ManagerBot.answer` still runs its full tool loop to completion first (nothing in `LLMClient`
  supports incremental generation), then the answer text is trickled to the client as a sequence of
  `message` events so the panel fills in progressively rather than blocking on the whole response -
  don't describe this as "streaming from the LLM" in future docs. Message/error event text is
  HTML-escaped server-side (`html.escape`) so htmx's default `sse-swap` (a raw innerHTML dump of
  `event.data`) can render it directly without executing anything a package's own content might
  contain; `citations` deliberately stays JSON on the wire rather than pre-rendered markup - building
  the `/console/packages/{id}?version=...#{field_path}` link shape is presentation logic that belongs
  to `ap_console`, not the format-neutral `ap_api` layer - so `base.html`'s one delegated
  `htmx:sseBeforeMessage` listener intercepts that named event, cancels htmx's default swap, and
  renders the citation links itself. A backend failure mid-request (LLM call raises) is caught in
  `chat_routes.py::_stream_answer` and reported as an `error` SSE event followed by `done`, never a
  hung connection or a bare 500 - `test_console_chat_stream.py` covers this against the same
  `_manager_bot_corpus` eval-set fixture P3.3's tests use, not synthetic UI-only content. The
  browser-side reconnect-loop fix (`base.html`'s `htmx:sseBeforeMessage` handler closing the
  `EventSource` on the `done` event) relies on real browser `EventSource` semantics that
  TestClient/pytest cannot exercise; it was verified via manual live-server SSE/curl testing rather
  than live-browser automation (no Chrome/Chromium binary in the sandbox this was authored in) - a
  deliberately accepted coverage gap, not an oversight - see the comment at the fix site.
- **`src/ap_manager_bot/`** (C4 manager bot) + `src/ap_api/chat_routes.py` (`POST /chat/manager`):
  a **tool-using loop, not embed-and-stuff RAG** (report 5.3) - `service.py::ManagerBot.answer`
  hands the LLM three read tools (`search_packages`, `get_package_summary`, `get_gate_report` -
  `tool_backend.py`) and lets it compose its own queries across turns, ending only via a fourth
  `provide_answer` tool. There is no other way out of the loop: a turn that returns no tool call at
  all (model stopped without calling anything) is treated as a refusal, not free text shipped
  uncited - see `service.py::ManagerBot.answer`'s "no tool_uses" branch.
  - **Scoping is double-checked, not just filtered once** (`scoping.py`): `confidentiality_filter_for(identity)`
    resolves the caller's role to the set of `confidentiality` values they may see *before* every
    `ap_index.search` call inside a tool; `chunk_in_scope(identity, chunk)` re-checks every chunk
    a tool is about to hand back to the model *after* the query - defense in depth against a filter
    that was built wrong or bypassed, per the bot-architecture research's pattern. Today this is two
    tiers (`internal` visible to any authenticated caller; `internal_restricted` additionally
    requires `analyst`/`reviewer`/`standard_approver`/`admin`) since no `team_id` exists yet (report:
    "team scope once teams exist") - the seam is this module, not its callers.
  - **Citations are enforced server-side, not just requested in the prompt** (`tool_backend.py`'s
    `ManagerBotTools._citable` registry + `service.py::ManagerBot._final_answer`): every ref_id a
    tool hands the model is recorded against the `Citation` it actually corresponds to; a
    `provide_answer` citation that doesn't resolve against that registry (invented, or dropped by
    the post-search scope check) is discarded, and if every citation on an answer turns out fake the
    whole answer downgrades to the same refusal path as an empty retrieval
    (`NO_EVIDENCE_ANSWER`) - never a partially-grounded answer shipped as if fully grounded.
  - **LLM egress**: `llm_client.py::AnthropicHTTPClient` speaks the Anthropic Messages API directly
    over `httpx` (no SDK dependency, per the apt-only sandbox note) - this is the captain-approved
    posture (resolved decision `fathm-phase3-readiness-decision-llm-egress-posture`, 2026-08-16):
    retrieved, redacted, in-scope package content may leave the premises to a frontier-model API at
    query time under that provider's no-training terms, as a documented deliberate inference-time
    exception to TRUST.md - do not swap providers without a matching captain decision. Model id is
    `AP_MANAGER_BOT_MODEL`-overridable, no default baked in as "the" approved one.
  - **Tests never call the real API**: `tests/_manager_bot_fake_llm.py::ScriptedLLMClient` is a
    second `LLMClient` implementation that plays the model's role deterministically (extract
    entity-looking tokens from the question, search, cite the top hit or refuse) - it exercises the
    real retrieval/scoping/citation harness end to end without network access or an API key;
    `test_manager_bot_llm_client.py` separately covers `AnthropicHTTPClient`'s own request/response
    shaping against `httpx.MockTransport`. `tests/_manager_bot_corpus.py` builds the C4 eval corpus
    (~8 packages via `ap_agent_tools.package_create`, rewritten with distinct supplier/part/override
    content, published+approved through the real `ap_review.ReviewWorkflow`, one package
    `internal_restricted` for the scoping tests) - `test_manager_bot_eval.py` is P3.3's ~15-question
    acceptance eval (each answer's citation checked against the known-correct package, plus an
    explicit no-match-in-corpus refusal case); `test_manager_bot_scoping.py` is the scoping and
    citation-contract acceptance tests.
- **Review queue** (P3.5, `GET /console/review-queue`): package-level review only (the resolved
  "review soundings = whole packages" reading) - `GET /packages?status=in_review` rendered as a
  queue with inline approve/reject, no row-level drill-down. Approve/reject post to a
  console-owned `POST /console/packages/{id}/review` (`routes.py::console_review_action`, distinct
  from `ap_api.app`'s own `POST /packages/{id}/review` - same underlying `ReviewWorkflow.transition`
  call, just reached via a form post instead of JSON) which re-renders
  `templates/_review_queue_table.html` in place (htmx `outerHTML` swap, mirroring the packages-list
  partial pattern) - a decided package simply drops out of the list. Because `get_console_identity`
  only resolves the session and never checks CSRF (unlike `ap_api.deps.identity_from_request`), the
  route calls `ap_console.deps.verify_console_csrf` itself before transitioning. `ConsoleCsrfInvalid`,
  `ReviewPolicyError` (self-review, gate-before-review failure, missing reject reason, wrong role),
  and `StoreError` are all caught in the route and rendered as an inline `.flash` message on the
  still-open queue, never a raw 500/403 - `ap_review`'s policy itself is untouched, this is purely a
  UI layer over it. The package detail page
  (`package_detail.html`) renders `PackageStore.audit_trail(...)` as a timeline - reads the same
  audit rows `GET /packages/{id}/audit` returns, no separate audit computation.
- **`src/ap_chat/`** (P3.6, C20 planner chat v0): fronts `POST /chat/manager` from a chat platform.
  Layered by design (`src/ap_chat/__init__.py`) so adding a second platform is a new adapter, not a
  rewrite: the top level (`core.py`'s `ChatPlatform`/`IncomingMessage`/`OutgoingReply`,
  `identity_map.py`, `manager_client.py`, `formatting.py`, `runner.py`) is platform-neutral;
  `ap_chat/telegram/` is the only adapter today (captain-decided: Telegram for v0, not Slack -
  resolved decision `fathm-phase3-readiness-decision-chat-platform`, 2026-08-16) - long-polling
  `getUpdates` via plain `httpx` (`telegram/client.py`), never a webhook, so no public HTTPS
  ingress is needed on the Pi. Identity mapping is an **explicit allowlist file**
  (`identity_map.py::IdentityAllowlist`, Telegram user id -> `{fathm_user_id, token}`), never
  auto-provisioned - an operator must have already run `ap-auth adduser --no-password` +
  `ap-auth token` for that person; per-team-member bot *provisioning* itself is tracked separately
  (`fathm-phase3-team-bot-provisioning`, out of scope here). `runner.py::BotRunner.run_forever` owns
  reconnect/backoff (exponential, capped, reset on the next successful poll) around any
  `ChatPlatform.poll()` failure - this lives in the platform-neutral runner, not the Telegram
  adapter, so a future Slack adapter gets the same resilience for free. Posting policy (captain
  decision `fathm-phase3-readiness-decision-chat-answer-posting-policy`, 2026-08-16): full answer
  text with citations, in-thread - citations render as links into the P3.4 console's package detail
  page (`formatting.py::package_console_url`, needs `AP_CHAT_CONSOLE_BASE_URL`). Setup (BotFather
  registration, `ap-auth` provisioning, allowlist format, systemd unit): `docs/telegram-bot-setup.md`;
  the systemd unit itself is `deploy/systemd/fathm-chat-telegram.service`. Console script:
  `fathm-chat-telegram` (`ap_chat.telegram.__main__:main`). Tests mock both HTTP boundaries
  (`httpx.MockTransport`, same seam pattern as `ap_manager_bot.llm_client.AnthropicHTTPClient`) -
  no real Telegram bot/chat credentials exist in this sandbox; `test_chat_telegram_e2e.py` is the
  full simulated round-trip, `test_chat_runner.py` is the reconnect/backoff acceptance test.

## `fathm-ap` MCP server + `fathm-planning` skill (P4 agent-draft capture)

Concretizes C8's "Tool/API defs agents can call" acceptance item, plus the P4 `agent_draft` capture
path the `agent_draft_present` check (above) only *detects* the absence of. Design authority:
`data/fathm-contract-enforcement-research/report.md` §6 in the firstmate repo - capture must happen
at tool-call time, while the agent's reasoning is still in context; the gate is a bypass detector,
not the capture mechanism.

- **`src/ap_mcp/`** is a thin JSON-RPC-2.0-over-stdio MCP server, stdlib + `jsonschema` only (no
  `mcp` SDK dependency - this repo's dev sandbox has no `pip`). `ap_mcp/server.py::handle_request`
  is the pure, directly-testable core (`initialize` / `tools/list` / `tools/call`); `main()` just
  wires it to stdin/stdout. Console script: `fathm-ap-mcp` (`ap_mcp.server:main`).
- **`ap_mcp/tools.py`** exposes four tools - `package_create`, `package_check`, `package_finalize`,
  `override_record` - and reuses `ap_agent_tools.tools` (`package_create`/`package_check`/
  `package_publish`) for the first three; no parallel gate or publish logic. `package_finalize` is
  `package.publish` under MCP naming.
- **`override_record` is the P4 capture tool.** Its schema requires `field_path`, `before`, `after`,
  `reason_code`, and **`draft_reason_text`** - the agent's rationale, so the call structurally
  cannot omit it. The server writes the override row with `reason_code`/`reason_text`/`author`
  seeded from the same call (row is immediately schema-valid) *and* `agent_draft: {reason_code,
  reason_text}` preserving the draft verbatim; a later human edit of the top-level fields (existing
  C10 review flow) never touches `agent_draft` - capture doesn't depend on acceptance.
- **Server-side validation mirrors the advertised schema by construction**: `ap_mcp/errors.py::validate_arguments`
  validates every call against the exact same schema object returned by `tools/list`
  (`TOOL_SCHEMAS[name]["input_schema"]`), one source of truth - avoids the MCP ecosystem's
  documented schema/enforcement-drift bug class. Rejections raise `ToolValidationError` with one
  planner-serving line per field (which field, how to fix, "now, while the reasoning is still in
  your context"), mirroring the gate's `evidence[]` style.
- **`skills/fathm-planning/SKILL.md`** is the distribution mechanism (agentskills.io spec:
  YAML frontmatter + Markdown body) - the C8 six-MUSTs as operating instructions, the override
  workflow ("propose every override through `override_record`, never write `labels/overrides.jsonl`
  by hand"), and the MCP server config to point a harness at. `tests/test_fathm_planning_skill.py`
  validates the frontmatter shape itself, not just that the prose reads like a skill.
- Out of scope here (explicitly deferred, per the design report §6 item 4 / §7): a conformance-eval
  admission gate for third-party agent integrations - not needed while fathm configures every
  design-partner bot itself.

## Phase 4 (in progress): C6/C7 Standard-change proposal storage and workflow

Implements the proposal storage/workflow/API foundation Phase 4's evolution loop sits on -
`data/fathm-phase4-readiness/report.md` §5.4 in the firstmate repo is the design authority; C6/C7
are `docs/DESIGN-FATHM-SYSTEM.md` sections 10/11. The drafting bot that populates real `diff_json`
content (§5.3), the apply mechanism (versioned profile registry + exported code-change specs, §5.5),
and the dry-run engine (§5.6) are all separate, later tasks - this slice is storage + state machine
+ JSON API only.

- **`src/ap_proposals/`** (`db.py` + `store.py` + `workflow.py` + `models.py` + `kinds.py` +
  `policy.py`) is a **sibling SQLite database** at `<store_root>/proposals.sqlite3` - not new tables
  in `ap_store`'s `index.sqlite3` - for the same reason `ap_auth`'s `auth.sqlite3` is its own file
  (see that module's docstring): proposals are Standard-governance state, a different domain with a
  different lifecycle than package metadata. It is also not a file sidecar like the C14 redaction
  report - proposals are mutable workflow state with queries ("all pending"), which is exactly what
  a sidecar isn't. Same connect/RLock pattern as `ap_store.db`/`PackageStore` and
  `ap_auth.db`/`AuthStore`: one `check_same_thread=False` connection guarded by an `RLock`, since
  `ap_api`'s FastAPI sync handlers run in threadpool worker threads.
- **State machine**: `pending_hitl -> approved | rejected | withdrawn` (`ap_proposals/workflow.py`'s
  `TRANSITIONS`). Approve-with-edits is `approved` with `edited_diff_json` populated, not a fifth
  state - `ProposalStore.set_status`'s `edited_diff` param writes it *beside* `diff_json`, never
  over it, so the original proposed diff always survives a human edit. There is no `applied` state:
  `ProposalStore.set_status` accepts `edited_diff`/`applied_version` in the **same transaction** as
  the decision (`COALESCE`-guarded UPDATE) - this is the extension point the later apply-mechanism
  task wires into, so "approved but silently unapplied" cannot exist by construction once that task
  lands. `ProposalPolicy.require_dry_run_for_declarative` is a documented-but-unenforced flag for
  that same later task (the dry-run engine doesn't exist yet, so nothing can honestly require it).
- **Policy/mechanism split** mirrors `ap_review.ReviewWorkflow`/`ap_store.PackageStore` exactly:
  `ProposalWorkflow` (`ap_proposals/workflow.py`) owns policy (`standard_approver` role required to
  decide, admin bypass; reject requires a non-empty `decision_reason`; an `edited_diff` is only
  valid on an approve decision and is itself schema-validated against the proposal's `kind`);
  `ProposalStore.set_status` owns mechanism (compare-and-swap + `proposal_audit` row, mirroring
  `package_audit`). **Creating a proposal has no role restriction** - any authenticated identity may
  call `ProposalWorkflow.create` (today's only caller is the sweep's service identity; a human-filed
  proposal route is a future API addition, not a policy or schema change) - deliberately not
  encoding a "bot vs. human" identity type anywhere.
- **`diff_json` is schema-validated per `kind`** (`ap_proposals/kinds.py`'s `DIFF_SCHEMAS` +
  `validate_diff`, same `jsonschema`-based pattern as `ap_mcp.errors.validate_arguments` - one
  source of truth, planner-serving `ProposalValidationError` messages). The four kinds
  (`standard_change | profile_change | reason_code_add | check_add`) each get a deliberately
  minimal/stub shape - the real shapes belong to the drafting bot and apply-mechanism tasks, not
  this one.
- **API** (`src/ap_api/proposal_routes.py`, mounted in `ap_api/app.py`): `GET /proposals`,
  `POST /proposals`, `POST /proposals/{id}/decision` - JSON, same auth discipline as the package
  routes (`identity_from_request`, no anonymous access; reads unrestricted by role, single-tenant).
  Role enforcement for decisions lives in `ProposalWorkflow.decide` (raised `ProposalPolicyError` ->
  403), not a route-level `require_any_role` dependency - mirroring how `POST /packages/{id}/review`
  lets `ReviewWorkflow` own the role matrix instead of double-gating at the route.
  `ap_console` will read `ProposalStore` directly once a console tab exists, same module-boundary
  pattern as the P3.5 review queue - no console UI is built by this slice.

## Gold-pack regression

`examples/commodity-commit-v1` must always pass `ap-gate check`. `.github/workflows/ci.yml` and
`tests/test_example_passes.py` both enforce this - if you change a check or the example, run
`ap-gate check examples/commodity-commit-v1` before committing.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
