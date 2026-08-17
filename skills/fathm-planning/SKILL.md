---
name: fathm-planning
description: Operating instructions for any planning agent that creates, edits, or overrides a fathm Analysis Package. Use whenever a task involves an ap-0.2 package - creating one, changing outputs, or recording a planner override - so every action goes through the fathm-ap MCP tools instead of hand-edited files.
license: MIT
metadata:
  fathm_standard_version: ap-0.2
  requires_mcp_server: fathm-ap
---

# fathm planning agent contract

You are a planning agent operating on a fathm Analysis Package (ap-0.2). This skill is the
distribution mechanism for the C8 agent runtime contract (`docs/DESIGN-FATHM-SYSTEM.md` section
12) - it is not documentation to remember, it is the operating procedure you follow for every
package action in this session.

## Setup: the `fathm-ap` MCP server

This skill assumes the `fathm-ap` MCP server is configured in your harness's MCP client config,
pointed at this repo:

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

(Or, without an editable install: `"command": "python3", "args": ["-m", "ap_mcp.server"]` with
`PYTHONPATH` set to the repo's `src/`.) It advertises four tools: `package_create`,
`package_check`, `package_finalize`, `override_record`. If the server is not connected, stop and
tell the operator instead of editing package files directly.

## The six MUSTs (C8)

Every action you take on a package MUST:

1. **Open/create the package before mutating outputs.** Call `package_create` (or work inside an
   already-created package directory) before writing anything under `outputs/`.
2. **Pin inputs and method.** Do not silently swap an input file or method after `as_of` is set;
   if the method changes, that is a new package version, not an edit in place.
3. **Write overrides to labels through the tool, never by hand.** Call `override_record` for every
   planner override. Never open `labels/overrides.jsonl` in an editor and append a line yourself -
   see "The override workflow" below for why.
4. **Emit only `output_contract` paths.** Do not write files outside the manifest's declared
   output contract.
5. **Call the same gate before claiming final or published.** Call `package_check` and read its
   `overall` field before telling anyone the package is done. `package_check` runs the exact same
   `ap_gate` library logic as `ap-gate check` and CI - there is no separate, looser bar for agents.
6. **Do not use chat memory as the system of record after the turn.** Anything that matters must
   land in the package (manifest, labels, outputs) before your turn ends - a fact that only exists
   in this conversation's history does not exist for review, audit, or the gate.

## The override workflow

**Propose every override through `override_record`. Never write `labels/overrides.jsonl` by
hand.**

`override_record` requires `field_path`, `before`, `after`, `reason_code`, and
`draft_reason_text` - your own one-to-few-sentence rationale for the override, given at the moment
you call the tool. This is not optional decoration: the tool call cannot succeed without it, because
that is the only moment your reasoning is still in your context. Once you move on to the next
field, the rationale is gone if it wasn't captured here.

The server writes your draft into the row's `agent_draft.reason_text` (and `agent_draft.reason_code`),
alongside top-level `reason_code`/`reason_text`/`author` seeded from the same call. A human reviewer
may later edit those top-level fields (correct the reason code, rewrite the text, sign it as
themself) through the existing review flow - your draft in `agent_draft` is never touched by that
edit. Capture does not depend on the human accepting your suggestion; it happened the moment you
called the tool.

Do not pad `draft_reason_text` to satisfy a length check, and do not invent a rationale you don't
have - if you genuinely have no reasoning beyond "the planner told me to," say that. A short, honest
draft is worth more than a fabricated detailed one; nothing downstream treats `agent_draft` as proof
of your internal computation, only as your stated rationale at the time.

## Tool reference

| Tool | When to call it | Notes |
|---|---|---|
| `package_create` | Starting a new package | Scaffolds from a profile template; never overwrites an existing directory |
| `package_check` | Before claiming a package is final, and any time you want gate feedback | Same `ap_gate` logic as `ap-gate check` / CI; read `overall` and `evidence[]` |
| `override_record` | Every planner override, without exception | Requires `draft_reason_text`; see above |
| `package_finalize` | Handing the package to the store for review | Publishes to `ap_store.PackageStore`; does not require `package_check` to pass first, but you should check first anyway (MUST #5) |

If a tool call is rejected, the error message names the field and how to fix it - fix it and
retry in the same turn, while your reasoning is still available, rather than deferring the fix to
a later turn.

## Check for a Standard update at session start

The Standard (profile rules: reason-code allow-lists, labels-row shape, etc.) can change under
you between sessions - a captain-approved proposal (C6/C7) may have bumped a profile's version.
Call `GET /standard/versions` at the start of a session to see the current version and changelog
for every profile in play before you start writing overrides against it.

You are not required to poll for this yourself beyond that one session-start check, and a missed
check is not a silent failure: **the gate's version pinning is the actual enforcement, not this
check** - `package_check` (and CI's `ap-gate check`) resolves a manifest's declared profile
version against the same registry, and (where a deployment has turned on the fail-closed knob)
refuses an unrecognized version outright rather than silently falling back to older rules. A
Telegram notification may also announce a new version to the team chat when one lands, but that is
a courtesy for humans, not something this skill's contract depends on - `GET /standard/versions`
is the pull surface built for you.

## Out of scope for this skill

This skill does not cover package review/approval (`ap_review`, the human-facing C10 flow) or
package store administration - those are operator/reviewer actions, not planning-agent actions.
