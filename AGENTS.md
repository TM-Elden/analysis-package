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
see "Phase 4" below), and **phase-5-in-progress** (`src/ap_lifecycle/` - C12 package lifecycle:
supersede, recall, legal hold, retention marker, purge; see "Phase 5" below). Brand is
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
  - **Answer formatting is prompt-only, not a template concern** (captain feedback with a real
    screenshot: citation-dense answers read as one hard-to-scan paragraph on a phone):
    `_SYSTEM_PROMPT` asks for a plain-language lead sentence stating the business fact, then a real
    newline, then supporting detail (dates, quantities, reason codes, override/exception ids) -
    detail set apart, not woven into the lead sentence's grammar; when there is more than one
    distinct supporting fact (quantity change, reason code, citation/contract reference,
    associated exception id, etc.), each one gets its own dash-prefixed line rather than being
    stacked into a single semicolon/comma-joined run-on sentence - a worked example pair (bad
    run-on vs. wanted multi-line shape) is inlined in `_SYSTEM_PROMPT` itself, since the abstractly-
    worded rule alone wasn't reliably followed (follow-up captain feedback with a real screenshot).
    The console's `.chat-answer` CSS already has `white-space: pre-wrap`, so a `\n` in `answer`
    renders as a line break with no template change needed. This is presentation guidance layered
    on top of the citation contract above, not a relaxation of it - see
    `tests/test_manager_bot_answer_formatting.py` for the lead/detail before/after and the
    run-on-vs-one-fact-per-line before/after, both through the same harness.
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
  auto-provisioned - an operator must have already provisioned that person a real fathm service
  account, via the console's Admin tab (P5.4, see "team-bot provisioning" below) or the
  `ap-auth adduser --no-password` + `ap-auth token` CLI fallback. `runner.py::BotRunner.run_forever` owns
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

## Phase 4 (in progress): C6 planner-bot evidence layer (`ap_planner_bot`)

Design authority: `data/fathm-phase4-readiness/report.md` section 5.2 in the firstmate repo. This
is stage 1 only (deterministic scan + detectors) - the LLM-drafting stage that turns a `Finding`
into a proposal, and the `ap_proposals` storage/workflow it writes to, are later chunks (P4.1/P4.4)
and do not exist yet.

- **`src/ap_planner_bot/scan.py`**: `scan_corpus(store)` pages through every `status == "approved"`
  package in a `PackageStore`, extracts each (`store.extract`, the same pattern as
  `ap_console.gate_report.render_gate_report_html` - read that module first), reruns the gate
  in-process (`ap_gate.checks.registry.run_all`, post-waiver outcomes), and parses
  `labels/overrides.jsonl` into `PackageScan`s. No persisted telemetry, no incremental state - a
  full scan recomputes from the store on every call (sub-second per package at pilot scale).
- **`src/ap_planner_bot/detectors.py`**: `run_all_detectors(scan)` runs the five v0 detectors
  (unknown/OTHER-heavy reason codes, repeated waivers, repeated override patterns, gate-failure
  hotspots including advisory-check fail rates, profile-version drift) over a `CorpusScan`,
  producing typed `Finding`s (`detector`, `kind` - a candidate proposal kind: `reason_code_add` |
  `profile_change` | `check_add` | `standard_change` -, `summary`, `package_ids`, `detail`). Pure
  functions, no I/O, no LLM call - the LLM (a later chunk) only narrates findings this module
  already computed. Thresholds are named constants at the top of the file, documented as tunable
  in place (same honesty pattern as the entropy threshold in `ap_redact/secrets_scan.py`). A
  "dead-end questions" detector is deliberately **not** built - no question log exists yet, and
  logging planner questions is itself inside the still-open
  `fathm-plan-review-decision-planner-incentive-stance` hold's territory (see below).
- **Hard invariant, non-negotiable: no detector aggregates by `author` or any `owners.*`
  identifier.** This is the mitigation the phase-4 plan adopts for that same open hold (report
  section 7): a bot whose input is "repeated overrides" is one `GROUP BY author` away from a
  planner league table. Enforced structurally, not just by convention -
  `scan.py`'s `OverrideRow` keeps only `field_path` / `reason_code` / `reason_text` from each
  parsed override row (`author`, `ts`, `before`, `after`, `evidence_refs`, `agent_draft` are
  dropped at parse time), so a detector cannot key off an author it was never handed.
  `tests/test_planner_bot_detectors.py::test_no_author_or_owner_keys_anywhere_in_scan_or_findings`
  asserts this on both the scan's own data and every `Finding.detail`. Extend this type or that
  test together if a future detector needs a new field.
- **Fixtures**: `tests/_planner_bot_corpus.py` builds two small seeded corpora off
  `ap_agent_tools.package_create` (mirroring `tests/_manager_bot_corpus.py`'s pattern) - a
  drift corpus with one injected instance of each of the five signals, and a clean corpus with
  none. Both use `ReviewPolicy(gate_before_review=False)` deliberately: several drift packages
  carry an intentionally-failing, unwaived check (the gate-failure-hotspot signal), which a real
  team only reaches `approved` for under that documented policy override - see the fixture
  module's docstring.

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
content (§5.3) is a separate, later task - this slice is storage + state machine + JSON API. The
apply substrate (versioned profile registry + gate resolution seam + dry-run, §5.5/5.6, see
"Standard registry, gate seam, dry-run" below) is wired to the decision itself - see "Apply-on-approve
mechanism" below for the transactional contract, the config-vs-code split, and the
dry-run-mandatory invariant.

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
  `ProposalStore.set_status` accepts `edited_diff`/`applied_version`/`spec_artifact_path` in the
  **same transaction** as the decision (`COALESCE`-guarded UPDATE) - `ProposalWorkflow.decide`
  performs the apply step (registry write or spec export) *before* ever calling `set_status`, so a
  failed apply never reaches it and "approved but silently unapplied" cannot exist by construction.
  `ProposalPolicy.require_dry_run_for_declarative` (default on) is enforced in `decide` - see
  "Apply-on-approve mechanism" below.
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
  `POST /proposals`, `POST /proposals/{id}/decision`, `POST /proposals/{id}/dry-run`,
  `GET /proposals/{id}/spec` - JSON, same auth discipline as the package routes
  (`identity_from_request`, no anonymous access; reads unrestricted by role, single-tenant).
  Role enforcement for decisions lives in `ProposalWorkflow.decide` (raised `ProposalPolicyError` ->
  403; a registry-apply failure raises `ProposalApplyError` -> 502), not a route-level
  `require_any_role` dependency - mirroring how `POST /packages/{id}/review` lets `ReviewWorkflow`
  own the role matrix instead of double-gating at the route. `POST .../dry-run` is intentionally
  not role-gated (see "Apply-on-approve mechanism" below). `ap_console` reads `ProposalStore`
  directly for its own Standard tab, same module-boundary pattern as the P3.5 review queue.
- **Console "Standard" tab** (P4 first cut, `src/ap_console/routes.py` `/standard*` routes +
  `templates/standard_*.html` / `_proposal_*.html` / `_dry_run_panel.html`): reads `ProposalStore`
  and calls `ProposalWorkflow.decide` directly, same module-boundary and
  `verify_console_csrf`-plus-inline-`.flash` pattern as the P3.5 review queue
  (`console_review_action`) - not a second copy of `ap_api/proposal_routes.py`'s JSON logic.
  `GET /console/standard` is the pending queue (status tabs swap `_proposal_queue_table.html` via
  htmx, mirroring `_review_queue_table.html`); `GET /console/standard/proposals/{id}` is the detail
  page (evidence links only render for the `{"package_ids": [...]}` evidence shape the P4 sweep
  detectors actually produce - `_evidence_summary` falls back to a bare count for any other shape);
  decisions (approve / approve-with-edits / reject) post to
  `POST /console/standard/proposals/{id}/decision`, which parses the edit textarea's JSON itself
  and re-renders `_proposal_detail_body.html` in place. `POST /console/standard/sweep` (the "Run
  planner sweep" button) now runs the real `ap_planner_bot` scan/detect/draft pipeline in-request
  (`fathm-p4-sweep` - see the dedicated section below). The dry-run panel
  (`_dry_run_panel.html`, driven by `POST .../dry-run`) only ever echoes the proposal's existing
  `dry_run_json` rather than triggering a run itself - the dry-run engine and its API trigger
  (`POST /proposals/{id}/dry-run`) exist now (see "Apply-on-approve mechanism" below), but wiring
  this console button to call `ProposalWorkflow.record_dry_run` is still a separate, unwired UI
  task; until then `dry_run_json` only gets populated by calling the API route directly. `GET
  /console/standard/changelog` remains a proposal-decision-history view (every non-`pending_hitl`
  proposal from `ProposalStore.list`), distinct from - not a substitute for - the now-real `GET
  /standard/versions` (registry versions + changelogs; see "Apply-on-approve mechanism" below).

## Phase 4 (in progress): standard registry, gate resolution seam, dry-run (C7 apply substrate)

Implements the apply substrate C6/C7's evolution loop sits on - `data/fathm-phase4-readiness/
report.md` §5.5/5.6 in the firstmate repo is the design authority. Wiring this to a proposal
decision (the real apply-on-approve trigger) is a later task; this slice is registry +
gate-resolution seam + dry-run only, all usable standalone today.

- **`src/ap_registry/profile_registry.py`**'s `ProfileRegistry(store_root)` is a **pure-filesystem**
  versioned store at `<store_root>/standard_registry/profiles/<name>/<version>/*.json` - no SQLite,
  unlike `ap_proposals`/`ap_auth`/`ap_store`: a version directory, once written, is never edited in
  place (`_write_version_dir` raises `ProfileRegistryError` if the target already exists), so there's
  no concurrent-mutation hazard a DB would need to arbitrate. `ensure_seeded(name)` copies the repo's
  vendored `profiles/<name>/*.json` tree in as version `"0.1"` the first time a name is touched
  (idempotent - a second call is a no-op); the repo tree remains the permanent default/seed, never
  written to. `bump_version(name, new_version, changed_files, ...)` is the real workflow write: reads
  the current version's files, applies `changed_files` on top (a `None` value deletes that file),
  writes the result as a *new* version directory, appends a `_changelog.jsonl` row, and flips
  `_pointer.json` to the new version - all via write-to-temp-then-`os.replace`, so a reader never
  observes a half-written version or a pointer aimed at one. `seed_version(name, version, files)` is
  the lower-level primitive (no changelog, no monotonic-version check) `ap_planner_bot.dry_run` uses
  to set up a scratch registry - not for real workflow writes.
- **`ap_gate/profiles.py`'s registry seam**: every `load_profile_*` loader now takes the manifest's
  *raw* `profile` value (e.g. `"commodity_commit_forecast/0.2"`, not the version-stripped short
  name) and resolves it registry-root-first, repo-`PROFILES_ROOT`-fallback. `profile_short_name`
  keeps its old contract (strips the version); `resolve_profile_declaration` is the new
  version-preserving parse. **Only call sites that pass a manifest's real declared profile value get
  version-aware behavior** - today that's `ap_gate/checks/labels.py`'s three checks
  (`reason_codes_known`, `labels_row_shape`, `agent_draft_present`); callers that only ever had a
  bare short name (`ap_redact`, `ap_planner_bot/detectors.py`, `ap_gate/field_path.py`) are
  unaffected and keep resolving straight to `PROFILES_ROOT`, by design (a declared version with no
  registry configured, or no version at all, always falls through - this is what keeps the
  `examples/commodity-commit-v1` gold-pack regression passing unchanged with the seam in place and
  no registry configured). Registry root and the fail-closed knob are resolved from
  `AP_STANDARD_REGISTRY_ROOT` / `AP_GATE_FAIL_CLOSED_UNKNOWN_PROFILE_VERSION=1` env vars by default,
  or passed explicitly as `registry_root=`/`fail_closed=` kwargs (what tests and
  `ap_planner_bot.scan`'s `_registry_root_override` context manager do instead of mutating env vars
  permanently). When the knob is on and the registry is configured but doesn't recognize the
  declared version, the loader raises `UnknownProfileVersionError`; each of the three check functions
  in `labels.py` catches that and turns it into a `CheckOutcome.fail` (never an uncaught exception
  out of `run_all`) - except `agent_draft_present`, which stays on `CheckOutcome.advisory_fail` here
  too, consistent with its "never fails core" invariant above: `training_grade.json` never got a
  chance to load, so its `require_agent_draft` opt-in is unknown, and an unrelated fail-closed knob
  must not be what escalates this check to blocking - see `test_gate_registry_seam.py`.
- **Cache lifecycle (the sharp edge this task exists to close)**: the old bare `lru_cache` per
  loader is gone. `_REGISTRY_FILE_CACHE` is keyed by `(registry_root, name, version, filename)`, not
  just `(name, filename)` - because a version's on-disk files never change after being written
  (`bump_version`/`seed_version` always create a *new* version directory), a cache hit for an
  already-resolved version can never go stale: any newly-written content necessarily lives under a
  key this cache has never seen. `bump_version`/`ensure_seeded`/`seed_version` also call
  `invalidate_registry_cache` defensively (belt-and-suspenders against a future in-place-edit escape
  hatch), but the version-keying is what actually makes "a registry write is visible on the very next
  read, same process, no restart" true by construction -
  `test_profile_registry.py::test_cache_invalidation_no_restart_needed` and
  `test_gate_registry_seam.py::test_registry_write_visible_on_next_gate_check_no_restart` both prove
  it end to end (loader-level and full `run_all`-level).
- **`src/ap_planner_bot/dry_run.py`**'s `dry_run(store, store_root, profile_name, proposed_files)`
  generalizes `ap_planner_bot.scan`'s scan-under-an-overlay capability (`scan_corpus`/`scan_package`
  gained an optional `registry_root` param; `scan.py`'s `_registry_root_override` context manager is
  what temporarily points the env-var seam above at a scratch root for one rerun) rather than
  reimplementing gate-rerun logic. **Deliberate non-obvious design point**: the overlay is written at
  the *same* version number every currently-approved package under `profile_name` already declares,
  not a new one - a real `bump_version` bumps the version and, by the version-pinning invariant
  above, an already-published package would never resolve to that new version on its own. But "which
  packages would newly fail" needs to be answered over the corpus that exists *today*, so dry-run
  simulates "this pinned version's files read as the proposal instead" (the design report's "as if
  republished under the proposal" framing) rather than a version nothing currently resolves to. The
  function is pure over the store + a throwaway scratch registry (`tempfile.TemporaryDirectory`,
  cleaned up before returning) - it never writes to the real registry and has no `ap_proposals`
  dependency (that wiring lives in `ap_proposals/apply.py::run_dry_run`, not here);
  `DryRunResult.to_dict()` is the JSON-serializable shape stored in a proposal's `dry_run_json` -
  see "Apply-on-approve mechanism" below. Diffing is per-package (`blocks_overall_pass()` flip ->
  newly-failing/newly-passing) and per-check (`CheckOutcome.result` string changed -> a
  `CheckMovement`, even when the package's overall pass/fail didn't move) - see
  `test_planner_bot_dry_run.py`.

## Phase 4 (in progress): apply-on-approve mechanism + `GET /standard/versions` (C7 wiring)

Connects the already-built pieces above - `ap_proposals` (storage/workflow) and the registry/dry-run
apply substrate - the last piece §5.4/5.5/5.6 needed. `src/ap_proposals/apply.py` is the pure
wiring module (`ProposalWorkflow.decide` in `workflow.py` is the only caller); it reuses
`ProfileRegistry` and `ap_planner_bot.dry_run.dry_run` unchanged, no gate/registry logic
reimplemented here. See `tests/test_proposal_apply.py` for the acceptance-level tests below.

- **Transactional apply-on-approve, declarative kinds only** (`profile_change`, `reason_code_add`):
  `ProposalWorkflow.decide` calls `ap_proposals.apply.apply_declarative` *before* it ever calls
  `ProposalStore.set_status`. `apply_declarative` seeds the profile on first touch
  (`ProfileRegistry.ensure_seeded`, idempotent), computes the changed-files patch from the
  proposal's effective diff (`compute_changed_files` - `profile_change` writes its `file`/`after`
  directly; `reason_code_add` reads the current `reason_codes.json` read-only and appends the new
  code), bumps the minor version, and flips the pointer (`ProfileRegistry.bump_version`, itself
  atomic via write-to-temp-then-`os.replace` - see the registry section above). There is no shared
  SQL/filesystem transaction (two different storage backends can't share one) - the transactional
  contract is enforced by **ordering**: if `apply_declarative` raises (wrapped as
  `ProposalApplyError`, a `ProposalStoreError` subclass), `decide` returns/raises before
  `set_status` is ever called, so the proposal is left exactly as it was (`pending_hitl`) by
  construction, not by cleanup - see `test_registry_write_failure_leaves_proposal_pending_hitl`.
  `applied_version` is written in the *same* `set_status` call as the decision, alongside
  `edited_diff`/`spec_artifact_path` (all `COALESCE`-guarded, see the state-machine bullet above).
- **Spec export for code kinds** (`standard_change`, `check_add`, `ap_proposals.apply.export_spec`):
  approval writes a markdown artifact (summary, rationale, the diff as approved, and the diff's
  optional `patch` field verbatim if present) to
  `<store_root>/proposal_specs/<proposal_id>.md`, and records that path (relative to `store_root`,
  posix-style) on the proposal as `spec_artifact_path`. No registry write, no code ever
  auto-applied - retrieval is `GET /proposals/{id}/spec` (`ap_api/proposal_routes.py`), which 404s
  if the proposal has no spec (declarative kinds and anything not yet approved). This is the
  concrete "human takes it into a normal PR" artifact §5.5 asks for, not a stub.
- **Dry-run is mandatory-at-decision, not decorative** (§5.6, `ProposalPolicy.
  require_dry_run_for_declarative`, default on): `decide` refuses to approve a declarative-kind
  proposal whose `dry_run_json` column is still `None`, raising `ProposalPolicyError` before any
  apply attempt. `ProposalWorkflow.record_dry_run(proposal_id, package_store)` is the "require it
  recorded first" half of that contract - it calls `ap_proposals.apply.run_dry_run` (thin wrapper
  over `ap_planner_bot.dry_run.dry_run`) and persists the result via
  `ProposalStore.record_dry_run` (a plain column update, deliberately **not** a status transition -
  no audit row, callable any number of times, each call overwriting the prior result). Exposed as
  `POST /proposals/{id}/dry-run` (deliberately not role-gated - running one changes nothing
  decision-relevant by itself; `decide` still independently policy-checks). Code kinds skip this
  entirely and `record_dry_run` refuses them outright (`ProposalPolicyError`) - you cannot dry-run
  a check that doesn't exist yet, so there is nothing to fake here, unlike the console dry-run
  panel's honest-stub echo (see the Console "Standard" tab bullet above, still a separate,
  unwired UI concern).
- **`GET /standard/versions`** (`src/ap_api/standard_routes.py`): supported `standard_version`s
  (`ap_gate.versions.supported_versions`, unrelated to profile versions) plus, per profile
  registry name (`ProfileRegistry.names()`, new - every name with a `_pointer.json`), its current
  version and full changelog (`ProfileRegistry.changelog`). Reads a `ProfileRegistry` rooted at
  `ProposalStore.root` (the shared store_root) directly - no proposal data involved, just the
  registry's own state - so this reflects a registry write from any source (a proposal approval,
  or a direct `ProfileRegistry` call in a script/test), not only proposal-driven ones. This is the
  pull surface a future notify/agent-docs task points agents at (§5.8).

## Phase 4 (in progress): C6 proposal-drafting service + sweep entry point (`fathm-p4-sweep`)

The piece that actually creates proposals - `data/fathm-phase4-readiness/report.md` §5.3 in the
firstmate repo is the design authority. Builds on the already-merged scan/detectors
(`ap_planner_bot/scan.py` + `detectors.py`), `ap_proposals` (storage/workflow), and the C4 manager
bot's `LLMClient`/`AnthropicHTTPClient`/`ScriptedLLMClient` seam (`ap_manager_bot/llm_client.py`) -
reused directly, not reimplemented.

- **`src/ap_planner_bot/service.py`** (`ProposalDrafter` + `draft_proposals`): one LLM turn per
  `Finding` - no retrieval loop like C4's Q&A, because the finding and its evidence are fully known
  up front (there is nothing further for the model to search for). `_fetch_evidence` fetches
  redacted chunks from `ap_index` for exactly the finding's own `package_ids` (never raw package
  bytes, same rule C4 follows), scoped through `ap_manager_bot.scoping`'s pre+post confidentiality
  double-check, and records `chunk_id -> package_id` in a per-finding citation registry - the same
  pattern `ap_manager_bot.tool_backend`'s `_citable` uses. Every approved+indexed package carries at
  least one `manifest_summary` chunk (`ap_redact.chunk.build_manifest_summary_chunk`), so a
  genuinely-indexed package always contributes at least one evidence ref.
- **Enforcement mirrors `_final_answer`'s citation registry, applied to a drafted diff instead of a
  chat answer** - all server-side, none of it prompt-only:
  - `diff` is schema-validated per `kind` (`ap_proposals.kinds.validate_diff`) before persist; a
    schema violation (or missing `summary`/`rationale`) discards the draft (`invalid_diff`) - never
    "fixed up" or stored raw.
  - `evidence[].ref_id` values are resolved only against that finding's own citation registry; an
    invented ref_id is dropped, and a draft whose evidence is entirely invented (nothing resolves)
    is discarded whole (`no_evidence_resolved`) - a partially-invented citation set never survives
    as if fully grounded, matching C4's "all-or-nothing" citation contract.
  - **Dedup**: `proposal_target(kind, diff)` (a kind-specific identity: `(profile, code)` for
    `reason_code_add`, `(profile, file)` for `profile_change`, `(target,)` for `standard_change`,
    `(check_id,)` for `check_add`) is compared against every currently-`pending_hitl` proposal of
    the same `kind`; a match discards the new draft (`duplicate`) - a re-run over the same drift
    signal never spams the queue with repeats. This also fires *within* one sweep when two distinct
    findings happen to draft the same target (see `test_planner_bot_service.py`).
  - A model turn that calls no tool at all is a considered decline (`declined`), not an error - not
    every finding need become a proposal, and this is not "no tool_uses -> refusal" (C4's fail-closed
    read of the same shape) but the opposite: silence here is a legitimate, expected outcome.
  - `draft_proposals` never lets one finding's bad draft abort a sweep - every discard reason is
    counted (`SweepDraftResult.discarded`), not raised.
- **`python3 -m ap_planner_bot.sweep`** (`src/ap_planner_bot/sweep.py`): the actual entry point.
  `run_sweep` is the plain library call (scan -> detect -> draft -> persist) both callers share;
  `main()` resolves identity via `identity_from_env` (systemd/CLI path) and the store/index roots
  via the same `AP_STORE_ROOT`/`AP_INDEX_ROOT` env-var convention `ap_api.deps` uses - resolved
  independently in this module rather than importing `ap_api`, since a sweep entry point is a peer
  of the interface layer, not a consumer of it. `deploy/systemd/fathm-planner-sweep.service` (oneshot)
  + `.timer` (weekly, mirroring the `fathm-chat-telegram.service` precedent) is the scheduled path;
  the console's "Run planner sweep" button (`ap_console.routes.standard_sweep`, previously a
  documented no-op stub) now calls `draft_proposals` directly in-request under the triggering
  session's own identity (not a service identity) - a full scan + draft pass is seconds at pilot
  scale, so no background job is needed there.
- **Egress**: covered by the same captain-approved inference-time exception as C4, extended to C6 by
  resolved decision `fathm-phase4-readiness-decision-llm-egress-c6-extension` (2026-08-16) - see
  `product/TRUST.md`'s exception paragraph, which now names C6 alongside C4. No new provider, no new
  posture - same Anthropic no-training terms, same data class (deterministic conformance stats +
  redacted evidence chunks).
- **Tests**: `tests/_planner_bot_corpus.py` gained `build_drift_corpus_with_index` /
  `build_clean_corpus_with_index` (same scenarios as the plain `build_*_corpus` the detector tests
  use, plus a populated `IndexStore` via `ap_index.reindex.reindex_package` - non-breaking additions,
  existing signatures unchanged). `tests/_planner_bot_fake_llm.py::ScriptedDraftingLLMClient` plays
  the model's role deterministically (mirrors `_manager_bot_fake_llm.py::ScriptedLLMClient`'s role:
  exercises the real schema-validation/evidence-resolution/dedup harness, not model judgment) for
  `test_planner_bot_service.py`'s eval bar (drift corpus -> expected proposal kinds with
  correctly-resolved evidence; clean corpus -> nothing) and `test_planner_bot_sweep.py`'s end-to-end
  `run_sweep` tests; `InventedEvidenceLLMClient`/`InvalidDiffLLMClient` are adversarial fakes for the
  two discard-path tests. `test_console_standard.py`'s fixture now also overrides `get_store` /
  `get_index` / `get_llm_client` for the sweep-button tests.

## Phase 4 (complete): C6/C7 notify-agents v0 (`ap_proposals.notify` + `ap_chat.telegram.notify`)

The last Phase 4 chunk - `data/fathm-phase4-readiness/report.md` §5.8 in the firstmate repo is the
design authority. Wiring, not a new subsystem: rides the already-merged `ap_proposals` (audit rows)
and apply-on-approve mechanism (changelog rows, version bumps) and the already-merged, already-live
`ap_chat` Telegram integration - explicitly **not** C16 (no HMAC webhooks, retry/backoff, or
payload versioning; see §11's exclusion).

- **`ap_proposals/notify.py`**'s `ProposalNotifier` is a `Protocol` (`notify_created` /
  `notify_decision` / `notify_version_released`), not an `ap_chat` import - same layering
  discipline as `ap_review` never importing `ap_index`. `ProposalWorkflow` gains an optional
  `notifier` field (default `None` = notifications off, not an error) and calls the hook *after*
  the real state change already committed (`ProposalStore.create`/`set_status` returned) -
  `create` fires `notify_created`; `decide` fires `notify_decision` for every approve/reject/
  withdraw, then `notify_version_released` too when a declarative approval's `apply_declarative`
  call actually bumped a profile version (`applied_version is not None`). Every hook call is
  wrapped in `ProposalWorkflow._notify` (broad `except Exception`, logged, never raised) - §5.8's
  "notification is a courtesy, not the contract" applies to delivery failures too: a Telegram
  outage must never fail a proposal decision.
- **`ap_chat/telegram/notify.py`**'s `TelegramProposalNotifier` is the concrete notifier - reuses
  `TelegramBotClient.send_message` directly (the same client `TelegramPlatform` uses to answer
  chat questions), just with no `reply_to_message_id` (these are proactive posts, not replies) to
  one configured `chat_id`. Messages are short and factual (proposal id, kind, one-line
  summary/outcome) by design - the console's "Standard" tab is where the full detail lives.
  `notifier_from_env()` builds one from `TELEGRAM_BOT_TOKEN` (existing) + `AP_CHAT_NOTIFY_CHAT_ID`
  (new; see `docs/telegram-bot-setup.md` §7) and returns `None` if either is unset - wired into
  `ap_api/deps.py::get_proposal_notifier` (feeds `get_proposal_workflow`, reaching both the JSON
  API and `ap_console`'s Standard-tab decision route, which share that one dependency) and into
  `ap_planner_bot/sweep.py::run_sweep`'s new `notifier` param (threaded from `main()`'s
  `notifier_from_env()` call for the weekly systemd sweep, and from the console's "Run planner
  sweep" button via the same `get_proposal_notifier` dependency).
- **Agent/CI pull surface**: `skills/fathm-planning/SKILL.md` gained a "Check for a Standard
  update at session start" section (`GET /standard/versions`) - notification is a courtesy nudge
  for humans, the gate's version-pinning/fail-closed knob (see the registry-seam section above) is
  what an agent must actually rely on, so the skill says that explicitly rather than implying the
  Telegram post is part of the contract.
- **Tests**: `tests/test_proposal_notify.py` covers the `ProposalWorkflow` hook-firing contract
  (created/decision/version-released, the courtesy-failure-swallow behavior, and
  `TelegramProposalNotifier`'s real request shaping against `httpx.MockTransport` - same seam
  pattern as `test_chat_telegram_client.py`). `tests/test_proposal_api_notify.py` proves the same
  end to end through the real (un-overridden) `ap_api.deps.get_proposal_workflow` dependency graph,
  not a hand-built workflow - every other proposal test file overrides that dependency directly,
  which would bypass this exact wiring.
- **This closes the Phase 4 loop end to end**: a proposal drafted by the sweep (P4.4) is reviewed
  and decided through the workflow/API/console (P4.1/P4.6), applied transactionally to the profile
  registry or exported as a spec artifact (P4.5), and now notified over Telegram (P4.7) - all seven
  dispatched chunks are merged.

## Phase 5 (in progress): Admin tab (users & access, index health, registry state, settings)

Implements `data/fathm-phase5-readiness/report.md` §5.3 in the firstmate repo plus the C14
redaction-visibility debt the Phase 3 report flagged and never discharged. One nav item **Admin**
(`base.html`, shown only when `"admin" in identity.roles`); every route under `/console/admin*`
(`src/ap_console/admin_routes.py`) is gated by `ap_console.deps.require_console_admin`, which
403s an authenticated-but-non-admin caller rather than redirecting (a redirect there would read as
a broken session, not a permissions wall) - a logged-out request still redirects to
`/console/login` via the usual `ConsoleAuthRequired` path. Same htmx-partial-swap/CSRF/inline-flash
patterns as the P3.5 review queue throughout (`_render` for full pages, `templates.TemplateResponse`
over a `_admin_*_body.html`/`_index_health_table.html` partial for every POST, `verify_console_csrf`
called explicitly before any mutation).

- **Users & access** (`/console/admin/users`, `/console/admin/users/{id}`): create user, edit
  roles, reset password, disable/enable, issue/revoke service-account tokens, per-user
  sessions/tokens view. `AuthStore.set_roles` (`src/ap_auth/store.py`) was the one genuinely
  missing store method; every mutation here (`create_user`/`set_roles`/`set_password`/
  `set_disabled`/`create_service_token`/`revoke_session_by_hash`) now takes an optional
  `actor: Identity | None` and writes an `auth_audit` row (`src/ap_auth/db.py`) - `actor=None` is
  reserved for the `ap-auth` CLI's bootstrap path (no HTTP identity exists yet), which stays
  unchanged and un-role-gated (it must work before the first admin can log in). **Last-admin
  guard**: `set_roles` (removing `admin`) and `set_disabled` (disabling) both refuse
  (`LastAdminError`, a subclass of `AuthError`) an edit that would leave zero enabled admin users
  - `AuthStore._count_enabled_admins` is the check, run before the mutation, inside the same
    lock/transaction as the read it's judging. Editing a *disabled* admin's roles, or re-enabling
    anyone, is never guarded - only a transition that would zero out the enabled-admin count is
  refused. The console never displays a raw token after issuance (shown once in the flash
  notice, same as `ap-auth token`'s one-time stdout print) and never accepts one back for revoke -
  `AuthStore.list_sessions`/`revoke_session_by_hash` operate on the stored `token_hash` (a sha256
  digest, not a secret) instead.
- **Index health** (`/console/admin/index-health`): every `approved` package whose
  `ap_redact.report.read_report` sidecar says `blocked=True`, with the detector hits/severity from
  that report and a "re-run redaction + reindex" button calling the real
  `ap_index.reindex.reindex_package` (the identical hook the review-decision path calls) - not a
  bespoke redaction re-run. A still-blocked package after the re-run is expected, not a bug:
  packages are immutable, so a genuinely-leaked secret only clears once a new version is
  published without it.
- **Registry state**: not a fifth screen - `GET /console/standard/changelog`
  (`src/ap_console/routes.py::standard_changelog`) was extended with a `ProfileRegistry(store.root)`
  table (current pointer version + seeded yes/no per profile), reusing the exact registry read
  `ap_api/standard_routes.py`'s `GET /standard/versions` already does.
- **Settings** (`/console/admin/settings`): `retention_days` lives in a new, audited
  `store_settings` KV table in `ap_store`'s `index.sqlite3` (`PackageStore.get_setting`/
  `set_setting`/`settings_audit_trail`, mirroring `store_settings_audit`'s
  old-value/new-value/actor/when shape after `package_audit`) - **not** `auth.sqlite3` (config is a
  store/tenant concern, credentials are a different blast radius; see `ap_auth.db`'s own reasoning
  in reverse). This task added the table; the later `fathm-p5-lifecycle` task (see below) adds a
  `retention_days` key on top of this same table and its audited `get_setting`/`set_setting`
  mechanism, unforked. The read-only effective-config panel (store/index/auth roots,
  registry root env var, model id env var, allowlist path env var) is a plain env-var dump, the
  lowest-priority item in this task's brief - trim it first if a future change needs the room.
- **Tests**: `tests/test_auth_store.py` covers `set_roles`/last-admin guard/`auth_audit` at the
  store level (including "a role edit changes a *live session's* resolved `Identity.has_role`, not
  just the DB row" - re-resolving the same still-valid session token after the edit, not just
  re-reading `list_users`). `tests/test_store_roundtrip.py` covers `store_settings`/its audit trail.
  `tests/test_console_admin.py` is the route-level suite: the full 403 matrix (every
  `/console/admin*` GET/POST for a non-admin identity, plus the nav item's own visibility), the
  last-admin guard refusing a real console POST (not just the store method), a role edit changing
  what a second live session can reach, and an index-health test that injects the same
  AWS-key-shaped secret `tests/test_ap_index.py::test_secret_salted_package_never_reaches_index`
  uses into a copy of the gold-pack example, publishes+approves it with `gate_before_review=False`,
  and asserts the console lists it as blocked.
## Phase 5 (in progress): C12 package lifecycle core (`ap_lifecycle`)

Design authority: `data/fathm-phase5-readiness/report.md` §5.1 in the firstmate repo; original
requirements are `docs/DESIGN-FATHM-SYSTEM.md` §13c (C12).

- **`src/ap_lifecycle/`** (`LifecycleWorkflow` + `LifecyclePolicy`) mirrors `ap_review.ReviewWorkflow`'s
  policy/mechanism split exactly, over the same `PackageStore.set_status` CAS + audit mechanism plus
  three new store mechanism methods (`link_replaces`, `set_legal_hold`, `purge`). **Union state
  machine**: `ReviewWorkflow.TRANSITIONS` (draft/in_review/approved/rejected) is untouched;
  `LifecycleWorkflow.TRANSITIONS` is a separate set layered on top of it -
  `approved -> superseded` (reviewer or admin; requires naming an existing *approved*
  `(package_id, package_version)` successor - no corpus gaps by construction; writes the successor's
  `replaces_package_id`/`replaces_package_version` via `PackageStore.link_replaces`, an audited
  column update distinct from the predecessor's own `status` flip), `approved -> recalled` (reviewer
  or admin, reason REQUIRED), `recalled -> approved` and `superseded -> approved` (admin only,
  unified as `LifecycleWorkflow.restore` - both are the same "only an admin reverses this" policy).
  A recalled/superseded package cannot re-enter `ReviewWorkflow`'s states except through `restore`.
- **Legal hold**: `legal_hold`/`legal_hold_reason` columns on `packages` (`PackageStore.set_legal_hold`,
  mechanism; `LifecycleWorkflow.set_legal_hold`, admin-only + reason-required-to-set policy). Hold
  blocks **purge only** - recall/supersede stay allowed under hold, deliberately: they are reversible
  status moves, and freezing them would let a hold keep bad content live in the corpus.
- **Retention marker**: reuses `store_settings` (the small generic key/value table in
  `index.sqlite3`, not `auth.sqlite3`, the P5.3 admin tab introduced - see above; store/tenant
  config, not credentials, self-auditing per row via `updated_at`/`updated_by_id`/`updated_by_roles`
  rather than routed through `package_audit`, since a setting here isn't scoped to one
  `(package_id, package_version)`) with a new `retention_days` key. `PackageStore.get_retention_days`/
  `set_retention_days` are thin wrappers over the same `get_setting`/`set_setting` mechanism;
  `LifecycleWorkflow.set_retention_days` is admin-only. No automatic deletion reads this value - it
  is purely a human-reviewed marker (a future retention screen, out of scope here).
- **Purge (`PackageStore.purge`) is the first genuinely irreversible operation in the product.**
  `LifecycleWorkflow.purge` is admin-only and refuses an `approved` or held package; `PackageStore.purge`
  re-checks both guards itself (defense in depth, the same double-check discipline
  `ap_manager_bot.scoping` applies to confidentiality - a caller reaching the store method by any
  path but the workflow still cannot destroy an approved or held package). Mechanism: **refcount the
  blob before deleting it** - `blob_sha256` is content-addressed and shared across `(package_id,
  package_version)` rows (two rows can share one blob only via direct row insertion today; the normal
  publish path can't produce this naturally since each package's own `package_id`/`package_version`
  are embedded in its MANIFEST.yaml bytes, which is why `test_lifecycle_workflow.py`'s refcount test
  inserts a synthetic second row directly - see that test's docstring), so the blob file is only
  unlinked when no other non-purged row references it (`SELECT COUNT(*) ... AND purged_at IS NULL`).
  Also deletes the C14 redaction sidecar (`ap_redact.report.sidecar_path` - safe for `ap_store` to
  import directly, since `ap_redact` has zero internal-project imports and there is no circularity
  risk, unlike `ap_index` below) and tombstones the row (`purged_at` set, `status` -> `'purged'`,
  content-bearing fields blanked - `title`/`as_of`/`owners_json`/`analyst_id`/`reviewer_id` - while
  `package_id`/`package_version`/`blob_sha256`/audit history survive) so audit rows, proposal
  evidence links, and supersede chains resolve to an honest "purged" record instead of dangling.
  **Purge does NOT touch the C4 search index itself** - `ap_store` cannot import `ap_index` (that
  would be circular: `ap_index.reindex` already imports `ap_store.store`), so a purge caller must
  separately call `IndexStore.remove_package(package_id, package_version)`. No `POST
  /packages/{id}/purge` route exists yet (purge is console-confirmed, and console UI is a separate,
  later task) - `LifecycleWorkflow.purge` is fully implemented and tested at the workflow/store layer,
  ready for a future console route to call.
- **Export**: `GET /packages/{id}/export?version=` (`ap_api/lifecycle_routes.py`) streams
  `BlobStore.get`'s bytes directly - the blob *is* the deterministic tar.gz. Requires the same
  elevated role set (`analyst`/`reviewer`/`standard_approver`, admin bypass) `ap_manager_bot/scoping.py`
  already uses for `internal_restricted` content, since an export is full raw bytes including
  unredacted author fields.
- **JSON API** (`src/ap_api/lifecycle_routes.py`, mounted in `ap_api/app.py`): `POST
  /packages/{id}/supersede`, `POST /packages/{id}/recall`, `POST /packages/{id}/restore`, `POST
  /packages/{id}/legal-hold`, `GET /packages/{id}/export` - thin routes over `LifecycleWorkflow`,
  `LifecyclePolicyError` -> 403 / plain `StoreError` -> 404 (no such package_version) or 409 (CAS
  conflict), mirroring `ap_api.app.review_package`'s error-code mapping exactly.

**The reindex-wiring fix (a real, live bug fixed alongside the above).**
`ap_index.reindex.reindex_package` was always correct - approved-only index membership, `redact_package`
+ `IndexStore.index_package`/`remove_package` - but before this task, nothing outside the test suite
ever called it: neither `ap_api.app`'s review route nor `ap_console.routes.console_review_action`
invoked it after a status transition, so in a live deployment **approving a package never actually
added it to the bot's searchable index**. The fix is wiring, not a workflow change:
`ap_api.deps.reindex_after_transition(store, index, package_id, package_version)` is now called from
every status-changing route - the existing review route (`ap_api.app.review_package`,
`ap_console.routes.console_review_action`) AND every new C12 lifecycle route except `export` (a
read) and `purge` (no route yet, and not wired through this hook regardless - see above). The call
is deliberately kept in the routes layer, never inside `ReviewWorkflow`/`LifecycleWorkflow`
themselves - preserving the existing rule that `ap_review` (and now `ap_lifecycle`) must not import
`ap_index`. `test_lifecycle_api.py::test_approve_reaches_the_index_and_recall_removes_it` is the
acceptance test: it drives the real HTTP routes (not `reindex_package` directly, unlike
`test_ap_index.py`) and asserts a newly-approved package's chunks are actually indexed, then that a
recalled package's chunks are actually gone.

## Phase 5 (in progress): gate-analytics dashboard (`GET /console/dashboard`)

Implements the C19 gate-dashboard remainder of §20a's Phase 5 - `data/fathm-phase5-readiness/
report.md` §5.2 in the firstmate repo is the design authority. Server-rendered Jinja2 + the
existing vendored htmx, same as every other console tab - no SPA, no charting library. Three
tiers, cheapest first, each a thin render over a computation engine that already exists elsewhere:

- **Hard invariant, non-negotiable: no dashboard tile, table, snapshot row, or template context
  is keyed by `author`, `analyst_id`, `reviewer_id`, or any `owners.*` identifier** - aggregation
  is by `check_id`/`reason_code`/`profile`/`status`/time only. This is the same rule
  `ap_planner_bot/scan.py`'s `OverrideRow` and the drift detectors already enforce (see Phase 4's
  section above); the dashboard is the first surface where it isn't automatic, because tier 1
  reads `PackageStore`'s `packages` table directly, which *does* carry `analyst_id`/`reviewer_id`.
  `PackageStore.stats()` (`src/ap_store/store.py`) is the one place that boundary is enforced by
  construction: its `GROUP BY`s are hardcoded to `status`/`profile`/`gate_overall` only, and it
  never selects the identifier columns at all - there is no filter to bypass because the columns
  are never read. `tests/test_planner_bot_detectors.py::test_no_author_or_owner_keys_anywhere_in_scan_or_findings`
  is extended (not duplicated) to also walk `ap_planner_bot.analytics`'s snapshot dict recursively
  for forbidden keys/values; `tests/test_console_dashboard.py` separately asserts the same against
  the real on-disk `snapshots.jsonl` and the rendered dashboard HTML.
- **Tier 1 - instant store stats** (`ap_store.store.PackageStore.stats()` -> `StoreStats`): package
  counts by status/profile, publish-time `gate_overall` distribution - plain SQL, no corpus scan.
  Review-queue and proposal-queue depth reuse the exact `ListFilter(status=..., page_size=1).total`
  pattern the review-queue/Standard-tab contexts already use elsewhere in `ap_console/routes.py`,
  not a new query shape. Always live: `dashboard()` and `dashboard_recompute()` both compute it
  fresh, cheaply enough to not need caching.
- **Tier 2 - fresh corpus scan** (`src/ap_planner_bot/analytics.py`'s `compute_corpus_analytics`):
  per-check fail rate post-waiver / waiver rate, reason-code distribution + OTHER share,
  profile-version mix, and the `agent_draft_present` advisory-check fail rate as its own tile -
  computed over the *same* `CorpusScan` object `ap_planner_bot.detectors.run_all_detectors`
  consumes (`ap_planner_bot.scan.scan_corpus`), one computation engine feeding both the drift
  detectors and the dashboard, never two. Pure function, no I/O - `ap_planner_bot.snapshot_store`
  is the separate module that persists its output. The current `run_all_detectors` findings render
  alongside as a "drift signals" list linking into the Standard tab, where any resulting proposals
  already live - the dashboard does not duplicate proposal storage or drafting.
- **Tier 3 - trend over time** (`src/ap_planner_bot/snapshot_store.py`): one JSON line per run,
  append-only, at `<store_root>/analytics/snapshots.jsonl` (write-to-temp-then-`os.replace`, same
  atomic-write pattern `ap_registry.profile_registry` uses - a reader never observes a torn line).
  `ap_planner_bot.sweep.run_sweep` appends a row on every call (the weekly systemd timer and the
  Standard tab's "Run planner sweep" button both call it, so trend recording rides along for free -
  no new job, no new infrastructure) using the exact scan it already ran for detection; the
  dashboard's own "Recompute now" button (`POST /console/dashboard/recompute`) runs a second,
  independent live `scan_corpus` + `compute_corpus_analytics` + `append_snapshot` (it does not
  call `run_sweep`, since a dashboard refresh must not also draft proposals) and swaps in only the
  `#dashboard-live` fragment - tier 1 doesn't need recomputing on that click.
- **Freshness**: `GET /console/dashboard` renders tier 1 (live) + tier 2/3 from the *latest
  recorded* snapshot (`ap_planner_bot.snapshot_store.read_snapshots`) - no scan on page load, per
  the brief's freshness choice. Drift signals are the one thing that never comes from a snapshot
  (a snapshot row is aggregate stats only, not findings) - the initial page load shows an honest
  "click Recompute now" note there rather than stale or fabricated findings; only a live scan
  (button or sweep-adjacent code path) populates that list.
- **Templates**: `ap_console/templates/dashboard.html` (page shell, tier 1) `{% include %}`s
  `_dashboard_live.html` (tier 2 + drift signals + tier 3), the same partial both the initial page
  render and the recompute button's htmx swap use - one markup, matching the
  `_proposal_queue_table.html`/`_packages_table.html` precedent. Rates render as CSS width-percent
  bars (`.bar-track`/`.bar-fill` in `base.html`), not an SVG/JS charting library, per the brief.

## Phase 5 (in progress): team-bot provisioning (`/console/admin/team-bot`)

Implements `data/fathm-phase5-readiness/report.md` §5.4 in the firstmate repo - absorbs the queued
`fathm-phase3-team-bot-provisioning` task. Replaces the manual operator steps
`docs/telegram-bot-setup.md` §2/§3 documented (still there as the bootstrap/headless fallback) with
one Admin-tab console flow, same `admin_routes.py` module and `admin`-role gate as the rest of the
Admin tab (see above) - no new role.

- **Provision** (`admin_provision_team_bot`) composes three existing primitives in one POST:
  `AuthStore.create_user(password=None)`, `AuthStore.create_service_token`, and
  `ap_chat.identity_map.add_entry` (new write helper, write-temp-then-`os.replace` in the
  allowlist's own directory - same pattern as `ap_registry.profile_registry`'s pointer writes).
  Not a real cross-store transaction (a SQL DB and a JSON file can't share one) - if the allowlist
  write fails after the user/token already exist, the route disables the just-created user
  (`set_disabled`, which also revokes the token) so a failed provision never leaves a live,
  unreachable account behind; see `ap_proposals.apply`'s "ordering, not a shared transaction"
  precedent for the same honest framing. The raw token is written straight into the allowlist file
  and never appears in the response, a flash message, or a log line - unlike the users & access
  tab's one-time-shown token issuance.
- **`ap_chat/identity_map.py`** gained `add_entry`/`remove_entry`/`read_entries` (module functions,
  not `IdentityAllowlist` methods - the console reads/writes the file directly, it doesn't hold a
  loaded `IdentityAllowlist` instance) plus `DEFAULT_ALLOWLIST_PATH`, now the one place both
  `ap_chat.telegram.__main__` and `ap_console.admin_routes` resolve the default from.
  `read_entries`/`add_entry`/`remove_entry` treat a missing file as empty (nobody provisioned yet);
  `IdentityAllowlist.load()` itself keeps its stricter startup contract (missing file -> fail
  closed) - see the module docstring for why the two must differ.
- **Runner reload-on-miss** (`ap_chat/runner.py::BotRunner._handle_message`): a resolve-miss now
  triggers exactly one `identity_map.load()` retry before refusing - the smallest change that
  makes a just-provisioned planner's first message work without bouncing the systemd unit. Not a
  file watcher, not per-message; a reload failure (or a miss that's still a miss after reload) is
  swallowed and falls through to the existing unauthorized-reply path, never a crash.
- **Revoke** (`admin_revoke_team_bot`): `set_disabled(user_id, True)` (already revokes every
  token) + `remove_entry` - the provision flow inverted, one button.
- **Access list**: `/console/admin/team-bot`'s GET renders allowlist entries joined to `users` rows
  (fathm user id, display name, most recent live bearer token's issue date, disabled state) via
  `_team_bot_context` - "who can talk to the bot" has one visible answer. An allowlist row whose
  user no longer exists renders as an explicit orphaned-entry state rather than erroring.
- A small `_admin_subnav.html` partial (included at the top of every `/console/admin/*` full-page
  template) cross-links users/team-bot/index-health/settings - previously each admin sub-screen was
  reachable only by typed URL.
- **Tests**: `tests/test_chat_identity_map.py` covers `add_entry`/`remove_entry`/`read_entries`
  (including "no leftover `.allowlist-*.tmp` sibling after a write" - the atomicity check).
  `tests/test_chat_runner.py` adds the reload-on-miss acceptance tests, both against a fake
  identity map (exact-one-reload-attempt behavior) and against a *real* `IdentityAllowlist` +
  `add_entry` (no restart needed, matching the acceptance criterion). `tests/test_console_admin.py`
  covers the full provision/revoke round trip end to end (`AuthStore` + the allowlist file, real
  `os.replace` atomicity, the last-admin/role/token assertions) and specifically asserts the raw
  token is absent from every rendered response.

## Gold-pack regression

`examples/commodity-commit-v1` must always pass `ap-gate check`. `.github/workflows/ci.yml` and
`tests/test_example_passes.py` both enforce this - if you change a check or the example, run
`ap-gate check examples/commodity-commit-v1` before committing.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
