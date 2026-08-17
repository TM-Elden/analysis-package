# Agent harness setup: pointing a planning agent at fathm

Implements NC.1 and NC.2 (`data/fathm-native-chat-readiness/report.md` §5.1/§5.2 in the firstmate
repo): the docs half of "turn the merged capture kit from 'exists in the repo' into 'a planner can
be pointed at it'", plus running that same harness from anywhere on the tailnet, not just the store
host. Code: `src/ap_mcp/` (the `fathm-ap` MCP server) and `skills/fathm-planning/SKILL.md` (the
operating-instructions skill a harness loads alongside it) - read both before this doc if you
haven't already; this is the setup/verification wrapper around them, not a restatement of the
tool contract.

The MCP server's six tools (`package_create`, `package_check`, `package_finalize`,
`override_record`, `package_submit_review`, `package_status`) run **local to the harness's machine**
in every mode - `package_create`/`package_check`/`override_record` always read/write a working-tree
package directory directly, since that's the planner's own workspace. `package_finalize`/
`package_submit_review` have two modes:

- **Local mode** (default): writes directly to a local `ap_store.PackageStore` root, no HTTP hop -
  the harness must run on (or SSH/tailnet into) the machine hosting the store the manager's
  console/API also reads.
- **Remote mode** (NC.2, `AP_API_URL` + `AP_API_TOKEN` both set in the MCP server's environment):
  `package_finalize` uploads the package over HTTP to `POST /packages/upload`;
  `package_submit_review` calls `POST /packages/{id}/review` - both against a running `ap_api`
  instance, authenticated by the bearer token. `store_root`/`actor_id`/`actor_roles` are ignored in
  this mode (identity comes from the token) - see §5 "Remote harnesses" below.

## 1. Provision a planner identity (`ap-auth`)

In **local mode**, the MCP server's `package_finalize`/`package_submit_review` tools take
`actor_id`/`actor_roles` arguments directly (self-declared, same-machine-tooling trust model - see
CLAUDE.md's C11 auth model note) rather than an HTTP bearer token, so there's no `ap-auth token`
step *required* to run the tools themselves. In **remote mode** (§5), the bearer token *is* the
identity - `ap-auth token` is required, not optional. There is still a real identity worth
provisioning even for local-only use, if this planner should also:

- be distinguishable in `package_audit`/review-queue history from every other planner, or
- eventually use remote mode (§5), which requires a bearer token, or
- log into the manager console to see their own packages - this one needs a real password, not
  `--no-password` (a `--no-password` user is service-account-only and `AuthStore`'s login check
  refuses it - see below).

Provision it now so all three are already true:

```bash
ap-auth adduser tom.planner --display-name "Tom Planner" --roles analyst --no-password
ap-auth token tom.planner   # prints a bearer token once - copy it now, it is not stored/shown again
```

If this planner should also log into the console, drop `--no-password` and set a real password
instead (interactively-prompted, or `--password` non-interactively) - `ap-auth adduser
tom.planner --display-name "Tom Planner" --roles analyst`.

`analyst` is the minimum role `package_submit_review` requires (`ReviewWorkflow._check_submit`);
add `reviewer` too only if this same person will also decide packages (self-review is blocked by
default - `ReviewPolicy.allow_self_review`, see CLAUDE.md). Use this `tom.planner` id as
`actor_id` and `analyst` (or `analyst,reviewer`) as `actor_roles` in every tool call below.

## 2. Configure the MCP server (`.mcp.json`)

Point the harness's MCP client config at `fathm-ap-mcp`:

```json
{
  "mcpServers": {
    "fathm-ap": {
      "command": "fathm-ap-mcp",
      "args": []
    }
  }
}
```

Without an editable install (this repo's apt-only dev sandbox, per CLAUDE.md's Build/test note):

```json
{
  "mcpServers": {
    "fathm-ap": {
      "command": "python3",
      "args": ["-m", "ap_mcp.server"],
      "env": {"PYTHONPATH": "/path/to/fathm/src"}
    }
  }
}
```

Where `.mcp.json` lives is harness-specific:

| Harness | Config location | Skill installation |
|---|---|---|
| Claude Code | `.mcp.json` in the project root (or `claude mcp add`) | Copy `skills/fathm-planning/` into the project's `.claude/skills/` (or the user-level skills directory) so it's discoverable as `/fathm-planning` / auto-loaded per its `description` |
| Any MCP-capable harness | its own MCP client config file/UI, same `command`/`args`/`env` shape | Load `skills/fathm-planning/SKILL.md`'s body as the agent's system/operating instructions - it's plain markdown, not Claude-Code-specific |

## 3. Verify: `fathm-ap-mcp --selfcheck`

Before trusting the server for real planner work, run:

```bash
fathm-ap-mcp --selfcheck
# or: PYTHONPATH=src python3 -m ap_mcp.server --selfcheck
```

This is the "is it plugged in" test: it starts the server in-process, sends real `initialize` and
`tools/list` JSON-RPC requests, then drives a scratch `package_create` -> `package_check` round
trip through the same dispatch path a live client uses, in a throwaway temp directory that is
always cleaned up (nothing it does touches your real store or working tree). It prints one
`[PASS]`/`[FAIL]` line per step and exits `0` only if every check passed:

```
[PASS] initialize
[PASS] tools/list advertises every implemented tool
[PASS] scratch package_create
[PASS] scratch package_check ran (gate result recorded, pass/fail not required)
selfcheck: all checks passed - the server is plugged in
```

A `[FAIL]` line here means fix the server/environment before debugging anything harness-side - the
harness's MCP client is not yet in the loop at this point.

## 4. Five-minute smoke test: the full authoring loop

With the server connected in a real harness session (skill loaded, `.mcp.json` pointed at it), run
through the loop the `fathm-planning` skill documents end to end. Pick a scratch `store_root`
(e.g. `/tmp/fathm-smoke-store`) distinct from any real store for this first run:

1. **Scaffold**: ask the agent to start a new package (`package_create`). Confirm it reports a
   package directory and a fresh `package_id`.
2. **Record one override**: ask it to change one output value with a reason (`override_record`).
   Confirm the tool succeeded (it cannot succeed without a `draft_reason_text` - if the agent tries
   to skip it, the tool rejects the call and explains why).
3. **Check**: ask it to check the package (`package_check`). Confirm `overall: "pass"` (the gold
   template always passes untouched; if you changed inputs, read `evidence[]` for what to fix).
4. **Finalize**: ask it to publish the package (`package_finalize`, pointed at your scratch
   `store_root`). Confirm it reports a `package_id`/`package_version` and `status: "draft"`.
5. **Submit for review**: ask it to submit for review (`package_submit_review`, same
   `package_id`/`package_version`/`store_root`, `actor_id`/`actor_roles` from step 1's `ap-auth`
   identity). Confirm it reports `status: "in_review"`.
6. **Confirm in the review queue**: start the console (`PYTHONPATH=src python3 -m ap_api`,
   `AP_STORE_ROOT=/tmp/fathm-smoke-store`) and check `GET /console/review-queue` (or
   `GET /packages?status=in_review` on the JSON API) for the package - it should be sitting there,
   ready for a reviewer to approve or reject.

If every step above works, the harness is genuinely plugged in and this is a real, reusable
planner setup - not just a passing selfcheck.

## 5. Remote harnesses (laptop over tailnet, NC.2)

A planner's harness (laptop, over Tailscale) can now publish and submit for review against the
store host's real `ap_api` server, without running on or SSHing into that machine. This is
**remote mode**: `package_finalize` uploads the package over HTTP to `POST /packages/upload`
instead of writing a local store; `package_submit_review` calls `POST /packages/{id}/review` the
same way. `package_create`/`package_check`/`override_record` are unaffected either way - they
always operate on the planner's own working tree, since that's where the analysis actually
happens.

### 5.1 Prerequisites

1. **`ap_api` is running and reachable on the tailnet** on the store host - e.g.
   `PYTHONPATH=src AP_STORE_ROOT=~/.fathm/ap_store python3 -m ap_api`, reachable at something like
   `http://pi.<your-tailnet>.ts.net:8000`. `ap_api` has no built-in TLS - either run it behind a
   reverse proxy that terminates HTTPS, or accept plain HTTP over the tailnet's own encrypted
   WireGuard tunnel (Tailscale's transport is already encrypted node-to-node; this is a materially
   different exposure than plain HTTP on the open internet, but says nothing about `ap_api`'s own
   transport security - treat `AP_API_TOKEN` as a real bearer credential regardless).
2. **A real bearer token for this planner** - §1's `ap-auth token tom.planner` step, run on the
   store host (or anywhere with `AP_AUTH_DB` pointed at the real `auth.sqlite3`). Copy it now; it
   is never shown again.

### 5.2 Configure the MCP server for remote mode

Add `AP_API_URL` and `AP_API_TOKEN` to the same `.mcp.json` env block from §2:

```json
{
  "mcpServers": {
    "fathm-ap": {
      "command": "fathm-ap-mcp",
      "args": [],
      "env": {
        "AP_API_URL": "http://pi.your-tailnet.ts.net:8000",
        "AP_API_TOKEN": "the token from ap-auth token tom.planner"
      }
    }
  }
}
```

Both must be set together - either alone leaves remote mode off (a URL with no token has no way to
authenticate; a token with no URL has nowhere to send it) and the tools fall back to local mode,
which will then fail on missing `store_root` (see Troubleshooting below) since a laptop has no
local store to point at.

### 5.3 What changes for the planner, concretely

Nothing about steps 1-3 of the §4 smoke test (`package_create`, `override_record`, `package_check`)
- those are always local. Steps 4-5 change shape: the agent no longer needs (and should not be
given) `store_root`/`actor_id`/`actor_roles` for `package_finalize`/`package_submit_review` -
identity comes from `AP_API_TOKEN`, and the store is wherever `AP_API_URL` points, not a
filesystem path the laptop can see. Verify with `GET /console/review-queue` (or
`GET /packages?status=in_review`) against the same `AP_API_URL`, same as the local-mode smoke test
verifies against a local server.

### 5.4 Upload endpoint auth and limits

`POST /packages/upload` requires the same auth as every other write route
(`Authorization: Bearer <token>`, `analyst` role) - no new auth model. The uploaded body is capped
at `AP_UPLOAD_MAX_BYTES` (compressed, default 50MB) and `AP_UPLOAD_MAX_UNCOMPRESSED_BYTES`
(declared uncompressed size from the tar's own member metadata, default 200MB, checked *before* any
member is extracted - the zip-bomb guard); an archive exceeding either is rejected (413) before
unpacking, and any archive member that would resolve outside the extraction directory (a `../` or
absolute-path entry, or a non-file/non-directory member such as a symlink) is rejected (400) before
any member is extracted - see `ap_api/upload_routes.py` and `ap_store.blobstore.extract_tar_gz`.

## 6. Troubleshooting

- **"Server not connected" / the skill's tools never appear**: the skill's setup section says to
  stop and tell the operator rather than editing package files directly - this is deliberate, not
  a bug to route around. Re-check `.mcp.json`'s `command`/`args`/`env` (does `fathm-ap-mcp` resolve
  on `$PATH`? is `PYTHONPATH` set if not installed?) and re-run `fathm-ap-mcp --selfcheck` directly
  in a shell first, outside the harness, to isolate a harness-config problem from a server problem.
- **`package_submit_review` rejected with a "gate-before-review policy blocks submission" message**:
  this is `ReviewPolicy.gate_before_review` (default on) working as intended - call `package_check`
  and fix what its `evidence[]` names before retrying, or ask an operator whether this store's
  policy should be relaxed (`ReviewPolicy(gate_before_review=False)`, a deliberate override, not a
  default).
- **`package_submit_review` rejected with an "requires the analyst role" message**: the `actor_roles`
  argument didn't include `analyst`, or the `ap-auth` identity used for `actor_id` wasn't
  provisioned with it (§1) - the tool call's `actor_roles` is self-declared, not looked up, so a
  typo there silently produces the wrong role set rather than an auth error.
- **`package_status` says "no such package"**: either the `package_id`/`package_version` doesn't
  match what `package_finalize` returned (copy it exactly - these are tool-call outputs, not
  something to guess), or `store_root` points at a different store than the one it was published
  to.
- **Scratch smoke test polluted a real store**: `store_root` is just a filesystem path argument -
  if you forgot to use a scratch one in §4, the smoke-test package is now a real (harmless, but
  extraneous) draft in your real store; delete it or leave it as `draft` (it never entered the
  review queue unless you also ran step 5 against the real store).
- **(Remote mode) `package_finalize`/`package_submit_review` rejected with a "required in local
  mode" message**: `AP_API_URL` and `AP_API_TOKEN` are not *both* set in the MCP server's
  environment, so the tools fell back to local mode and then found `store_root` missing - either
  set both (§5.2) or supply the local-mode arguments instead; there is no partial/mixed mode.
- **(Remote mode) upload rejected with a 401/403**: the token is invalid, expired, revoked, or
  belongs to an identity without the `analyst` role - re-run `ap-auth token tom.planner` on the
  store host and update `.mcp.json`'s `AP_API_TOKEN`, or check `ap-auth list` for the role.
- **(Remote mode) upload rejected with a 413**: the package exceeds `AP_UPLOAD_MAX_BYTES` or
  `AP_UPLOAD_MAX_UNCOMPRESSED_BYTES` (§5.4) - an operator can raise either env var on the `ap_api`
  process if the package is legitimately large.
