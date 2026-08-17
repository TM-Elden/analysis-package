# fathm vision lock (reframed)

**Date:** 2026-08-16  
**Status:** Canonical product vision - supersedes platform-first reading of DESIGN-FATHM-SYSTEM for near-term build and pitch.

---

## One sentence

**fathm enforces metadata standards inside the agent** (Hermes, clawbot, Cursor, custom bots, …) so every piece of analysis work is **documented in a standard Analysis Package shape** - not left as chat scrollback and naked spreadsheets.

---

## What we got wrong

| Over-indexed | Under-indexed |
|--------------|----------------|
| Standalone console / store / multi-bot SaaS | **In-agent** enforcement at draft and publish time |
| Manager chart-room as the product | Standard documentation of analysis work as the product |
| Planner-bot rewriting the Standard | Agent **must** emit/maintain package metadata |
| Full C1–C19 platform | Thin **contract + gate + agent adapter** |

Platform surfaces (store, query, HITL) can exist **later** as consumers of packages. They are not the point.

---

## What “good” looks like

When someone does analysis **with an agent**:

1. The agent works in (or writes to) an **Analysis Package** directory/layout.  
2. **Required metadata** is always present: inputs + as-of, method/how, outputs, human deltas with reason codes, QA/status.  
3. A **gate** runs before the work is allowed to count as done/published (in CI, hook, or agent tool).  
4. Incomplete work fails closed with a message the agent (and human) can fix.  
5. Downstream tools (review, manager ask, audit) only see **packages**, never raw chat as system of record.

The human still judges. The agent still drafts. **The standard is what stops the decision apparatus from evaporating.**

---

## Product shape (thin)

```
┌─────────────────────────────────────────┐
│  Agent runtime (Hermes / clawbot / …)   │
│    tools: init_pack | check | label |   │
│           publish_local                   │
└─────────────────┬───────────────────────┘
                  │ must produce
                  ▼
┌─────────────────────────────────────────┐
│  Analysis Package (ap/0.2 layout)       │
│  MANIFEST + inputs + outputs + labels   │
└─────────────────┬───────────────────────┘
                  │ ap-gate
                  ▼
            pass = “documented”
```

Optional later: upload store, chart room, org HITL - **all read packages**.

---

## Non-goals (for this vision)

- Replacing ERP / planning suites  
- Being “the” enterprise data catalog  
- Training a foundation model as the MVP  
- Forcing a separate web app for every keystroke  
- Chat transcript as the archive  

---

## Implications for demo

**Core demo = agent path produces a gated package.**

Planner-facing:
1. In agent: work the SSD (or demo) analysis  
2. Package metadata kept/updated by standard tools  
3. `ap-gate` / `package_check` fails until complete  
4. Override recorded with credit  
5. Gate passes → work is “documented”

Manager-facing (optional second beat):  
Open or query **that package** - not the chat.

---

## Implications for firstmate

Build priority:

1. **ap contract** (already mostly there)  
2. **ap-gate** (already there)  
3. **Agent adapter** - Hermes skill / clawbot tools / MCP that *forces* the loop above  
4. Stop expanding console/proposals/lifecycle until (3) is the happy path  

---

## Name map

| Term | Meaning under this vision |
|------|---------------------------|
| **fathm** | Product: make analysis fathomable via enforced standards in agents |
| **Analysis Package** | The standard documentation unit |
| **ap-gate** | Enforce the standard |
| **Chart room** | Later consumer of packages |
| **Team model** | Later Q&A over packages |

---

## Pitch line (internal)

> We don’t need another dashboard first. We need every clawbot/Hermes analysis to leave behind **standard documentation** - or it doesn’t count as done.
