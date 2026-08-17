# firstmate kickoff - fathm VISION REFRAME + core demo

**Handoff ID:** `fathm-vision-agent-standards-2026-08-16`  
**Supersedes:** `FIRSTMATE-CORE-DEMO.md` platform-leaning bits; keep P/M demo checkboxes but re-aim **how** they’re built.

## Vision (read this first)

**The whole point:** enforce **metadata standards inside the agent** (Hermes, clawbot, other agents) so analysis work has **standard documentation** (Analysis Package) - not chat + naked sheets as the record.

Full lock: `docs/VISION.md`

### Not the point
Standalone mega-console, proposal/registry platform, lifecycle suite, as the primary product.

### Is the point
Agent tools + gate such that **done = gated package with required metadata**.

---

## Build order (strict)

### 1. Agent adapter (PRIMARY)
Ship tools an agent must use (MCP and/or Hermes skill and/or simple CLI the agent calls):

| Tool | Behavior |
|------|----------|
| `pack_init` | Create ap layout + MANIFEST skeleton for a workflow (e.g. SSD forecast) |
| `pack_check` | Run ap-gate; return structured fails the agent can fix |
| `pack_label` / `override_add` | Append human/agent override with author, reason code, text |
| `pack_set_meta` | Set required manifest fields (inputs as-of, method summary, outputs) |
| `pack_publish` optional | Local store publish if already easy; else “gate pass = done” is enough |

**Enforcement:** agent runbook/skill says: you may not claim complete until `pack_check` is pass. Prefer hard fail in tool layer over polite docs only.

### 2. Keep gate + example pack green
`ap-gate check examples/commodity-commit-v1` + fail fixtures for missing labels/meta.

### 3. Planner demo (same 7 checks as before)
But driven **through the agent tools**, not only console clicking:
1. Agent draft path  
2. Package is the artifact  
3. Gate blocks incomplete  
4. Override with credit  
5. Gate pass  
6. Publish or “documented” stamp  
7. Reopen pack still has override  

### 4. Manager beat (thin, secondary)
One question → cite into package. Only after agent path works. Reuse existing ask if present; do not expand RAG.

---

## Stop / freeze
- New proposal workflow features  
- Lifecycle (recall/hold/purge)  
- Registry apply-on-approve polish  
- Multi-tenant auth expansion  
- New console screens not required for agent demo  

Use existing console only if it helps show the package; agent path is the hero.

---

## Branches / status
- Branch: `fm/fathm-agent-standards-demo`  
- Status: `~/firstmate/state/fathm-core-demo.status`  
- Report: `done: agent standards path — pack_* tools + demo script — PR <url>`

## Definition of done
A Hermes or clawbot-equivalent agent, using only project tools + gate, produces a **pass** Analysis Package for the SSD (or fixture) workflow with at least one credited override - without a human hand-editing YAML as the primary path.
