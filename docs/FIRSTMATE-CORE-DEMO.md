# firstmate kickoff - fathm CORE DEMO ONLY

**Handoff ID:** `fathm-core-demo-2026-08-16`  
**From:** Hermes / Tom  
**To:** firstmate / captain (PiSD)  
**Authority:** This brief **supersedes** feature expansion from `DESIGN-FATHM-SYSTEM` C10–C19 for near-term work. Full system docs remain reference; **do not build more platform** until core demo is green.

**Repo:** https://github.com/TM-Elden/fathm  
**Path:** Meta internal pilot (SSD forecast). Not YC/fundraise.

---

## Mission

Ship a **demo-complete** loop for the **planner workflow**, then a thin **manager ask** on top.  
Stop over-building proposals, lifecycle, registry polish, MCP, multi-tenant, etc.

### One-sentence proof
> Bot drafts the SSD forecast → human judgment is captured → it only counts when gated as a package → (manager) one question gets a cited answer.

---

## Phase P - Planner workflow demo (PRIORITY 1)

### Done when all are true (live or scripted demo ≤4 min)
1. Draft came from **agent path** (SSD forecast)
2. Artifact is an **Analysis Package** (not chat transcript)
3. **Gate blocks** incomplete publish (actionable fail)
4. Planner adds **one override** with author + reason code + plain why
5. **Gate passes**
6. **Publish** yields package id + version
7. Planner can **reopen this pack** and still see the override

### Exact demo steps to support in product
| Step | UX / API must support |
|------|------------------------|
| Open pack | View package layout: MANIFEST, inputs/, outputs/, labels/, qa/ |
| Gate check | Run ap-gate (button or CLI equivalent) with human-readable fails |
| Gate fail | e.g. missing reason on manual hold / missing declared output |
| Add override | labels/overrides.jsonl or UI: target, action/code, reason text, author |
| Gate pass | Re-check green |
| Publish | store.publish → id + version; immutability on same version |
| Reopen | Load published pack; show overrides list |

### Explicitly OUT for Phase P
- Planner bot / Standard-change proposals / dry-run-before-approve / registry apply
- Lifecycle: supersede, recall, legal hold, retention, purge
- MCP agent-capture kit polish (unless already needed to create the SSD pack)
- Multi-role auth beyond single user + optional reviewer
- Company bot, training export, L2 semantic CI
- Deployment packaging as a goal in itself

### SSD pack
- Prefer **real SSD forecast** package from Tom's chatbot workflow
- Fallback: thin SSD-shaped pack cloned from `examples/commodity-commit-v1` with SSD naming - mark as fixture
- Profile: reuse commodity_commit_forecast or minimal SSD profile if already exists; **do not** invent a large new standard

### Acceptance tests (must automate)
- Gold/example pack still passes gate
- Fixture: missing override/reason → gate fail
- Fixture: override present → gate pass → publish → get by id shows override
- No regressions that block `ap-gate check examples/commodity-commit-v1`

---

## Phase M - Manager ask demo (PRIORITY 2, after P green)

### Done when
1. At least one **published** SSD (or demo) pack in store  
2. Manager enters **one natural language question**  
3. Answer in plain English  
4. **Citation** opens/lands on the package and the relevant override or field  

### Example questions to support
- “Why is [SKU] on hold?”
- “Where did [number] come from?”

### Explicitly OUT for Phase M
- Perfect RAG quality
- Multi-team corpus
- Planner Standard HITL
- Fine-tuned model

### One-line product truth
> Model = Q&A over packages we already trust, with lineage. No package, no answer.

---

## Build rules

1. **Cut over create** - Prefer wiring existing `ap_gate`, `ap_store`, `ap_console` / ask path over new subsystems.  
2. **Demo path first** - If a feature is not on the P or M checklist, it waits.  
3. **Single tenant** - Tom + manager sponsor.  
4. **Readable fails** - Gate messages for planners, not stack traces.  
5. **Credit** - Override author is non-negotiable.  
6. **Branch naming** - `fm/fathm-core-demo-planner` then `fm/fathm-core-demo-manager`  
7. **Status file** - `~/firstmate/state/fathm-core-demo.status`  
   - Append sparingly: `working:`, `done:`, `blocked:`, `needs-decision:`  
8. **Do not** open new phase-4/5 feature work unless blocked on P/M.

---

## Suggested implementation order

1. Audit what already exists on `main` for: console pack view, gate button, override edit, publish, ask/query  
2. Gap-fill **only** missing P steps for a smooth 4-minute demo  
3. Script + checklist in `docs/DEMO-CORE.md` (planner then manager)  
4. One fixture pack under `examples/` or `tests/fixtures/` for SSD demo if real data can't live in git  
5. Phase M: single ask box over published packs with citations  
6. Stop and report `done: core demo P+M ready` with PR link(s)

---

## Reference (read, don't expand scope from)

- Manager pitch: `docs/PITCH-MANAGER-SSD.md` / `docs/html/fathm-manager-ssd.html`
- Path: `docs/PATH-INTERNAL-META.md`
- Standard: `standard/ap-0.2/STANDARD.md`
- Gate: `src/ap_gate/`
- Design full system: historical scope - **do not resume C10–C19 buildout**

---

## Definition of done (handoff complete)

Captain can run a **planner demo** meeting the 7 checkboxes and optionally a **manager cite** in the same session without touching proposals/lifecycle.

Report:
```
done: core demo P [and M] — PR <url> — demo script docs/DEMO-CORE.md
```
