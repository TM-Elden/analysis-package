# Manager pitch - commodity SSD forecast → fathm (internal)

**Audience:** direct manager + optional stakeholders (e.g. Curran, Ashwini, Gaia)  
**Length:** ~90 seconds spoken · one page written  
**Path:** Meta internal pilot (not startup pitch)  
**Vision:** [VISION.md](VISION.md) - enforce analysis metadata standards *in the agent*  
**Status:** Manager-ready · presentation HTML 2026-08-16  
**HTML (present this):** [`docs/html/fathm-manager-ssd.html`](html/fathm-manager-ssd.html)

---

## Verbal script (~90 seconds)

Through owning commodity **SSDs**, I automated the full forecast generation loop by talking to a chatbot.

I gave it my **upstream** sources.  
I taught it the **in-between** logic.  
I told it how to build every **downstream** report.

That works. It’s also the problem.

If the draft lives in a chat, we don’t get **lineage**, **data-quality checks**, **standardization**, or **governance** - and we can’t honestly say an AI-native leader can ask any question of our analysis and trust the answer.

**And every cycle we publish without capturing it, we throw the alpha away.**

The planner’s real product isn’t only the forecast tab. It’s the **decision apparatus**: which sources counted, what was overridden, why the hold, what truth got applied. That evaporates when the cycle ends - into chat scrollback and tribal memory. We spend the people cost to produce the judgment, then store almost none of it in a form agents or leaders can use again. **Cash and data, both on fire.**

We want two things that look like they conflict:

1. **Move fast with agents** on real, nonstandard planning work.  
2. **Traceability and an AI-native corpus** so someone like Curran, Ashwini, or Gaia can query the team’s work - not a pile of threads and sheets.

**fathm** is how we square that.

Every time a bot (or human) finishes a cycle, the unit of publish isn’t the chat - it’s an **analysis package**: pinned inputs, method, outputs, human overrides with credit, and a gate before it counts as published. On top of that, a **chart room** so leadership can ask the corpus and get answers with provenance.

**Two beats, one pilot:**

- **Beat A** - Agent is the primary draft surface for the SSD forecast (we already proved it’s possible).  
- **Beat B** - Nothing in-scope is “done” until it’s a gated package we can query later.

**Ask:** 90 days on this workflow. Success = agent-born drafts by default, 100% of in-scope publishes are packages with queryable lineage, and you (or a named sponsor) actually ask the chart room weekly. Expand, hand off, or kill at day 90.

I’m not asking for an org-wide platform or a headcount story. I’m asking to channel the clawbot reality we already have into something we can govern.

---

## One-pager (send ahead or leave behind)

### Title
**From chatbot forecast to governed analysis - SSD pilot (90 days)**

### What I already did
On **commodity SSDs**, end-to-end forecast generation runs through a chatbot:
- Upstream data sources → provided to the agent  
- In-between logic → encoded in conversation / instructions  
- Downstream reports → agent builds to spec  

**Result:** the process is automatable by talking to a bot. Adoption of clawbot-style tools is real but mixed - this shows the high end of what’s possible.

### The cost of waiting
Every publish that goes out **without** the planner’s decision apparatus (sources, logic, overrides, reasons) is alpha we paid for and did not keep.

| We burn | How |
|---------|-----|
| **Cash** | Same judgment re-earned next cycle; audit and rebuild tax |
| **Data** | Irreplaceable human deltas never land in a queryable corpus |
| **AI-native future** | Leaders can’t ask the team’s work; bots can’t learn *our* standards safely |

**Line for an AI-native manager:**  
> Every day we wait, alpha walks out of the building and into the trash - we pay for the decision once, then throw away the metadata that made it.

**Line for a skeptical manager:**  
> We’re already paying planners and bots. Without packages, we pay again next week for the same archaeology - and we still can’t answer where the number came from.

### The tension
Org goals include:
- **Traceability / lineage** of reporting  
- **AI-native** posture - leaders (e.g. Curran, Ashwini, Gaia) can ask any question of our analysis  

Chat-native work fights those goals:
| We need | Chat-only draft gives us |
|---------|---------------------------|
| Lineage | Broken or manual |
| DQ checks | Ad hoc |
| Standardization | Per-person prompts |
| Governance | After-the-fact |
| Query across the team’s work | Threads + drive archaeology |

**Question:** How do we get lineage, quality gates, queryability, standardization, and governance across **nonstandard** planning processes - without killing agent speed?

### Enter fathm
**fathm** = understand every analysis fully, down to its source.

For this pilot it means:

1. **Analysis package** - the publish unit (inputs + as-of, method, outputs, human judgment/overrides with credit, QA)  
2. **Gate** - doesn’t count as published until complete  
3. **Chart room** - managers/leaders query validated packages with citations  

Agents stay the **draft surface**. Packages are how drafts become **institutional**.

### Two-beat pilot (same 90 days)

| Beat | What | Success signal |
|------|------|----------------|
| **A · Surface** | Agent is default draft path for SSD forecast loop | Most cycles start in approved agent surface, not shadow one-offs |
| **B · Scale** | Every in-scope publish is a gated package | 100% packages with queryable lineage; sponsor queries weekly |

Beat A without B = faster unauditable sludge.  
Beat B without A = process with no traffic.

### Explicitly out of scope
- Org-wide mandate day one  
- Replacing ERP/planning suites  
- Headcount-reduction narrative  
- Training public models on internal content  
- Boiling the ocean on day one standards  

### Ask
| Need | Why |
|------|-----|
| Manager sponsorship | Air cover + chart-room user |
| SSD forecast as pilot workflow | Already proven agent-automatable |
| 90 days | Habit + kill criteria |
| Access to current data/report path | Meet the real process |

### Decision at day 90
**Expand** to adjacent commodities/workflows · **Hand off** to a platform owner · **Stop**.

### One line
> We already showed the forecast can be generated by talking to a bot. fathm makes that safe to scale - and stops us from paying for judgment once, then throwing the decision apparatus in the trash.

---

## Alpha / urgency lines (pick by audience)

**A · AI-native manager**  
Every day we wait, our alpha flies out the door and into the trash. Each publish without the planner’s decision apparatus is judgment we funded and did not keep.

**B · Operator / finance skeptic**  
We’re already burning cash on cycles we can’t replay. No metadata, no lineage - just another sheet and another “trust me.”

**C · Short**  
Pay once for the decision. Stop throwing away the apparatus that made it.

**D · Corpus angle**  
The chart room is empty until packages exist. Delay doesn’t freeze the world - it deletes the training signal and the audit trail for work we’re already doing.

---

## Tight email version (short)

Subject: Pilot idea - agent-drafted SSD forecast + governed packages (90 days)

I’ve automated commodity SSD forecast generation end-to-end through a chatbot (upstream sources, logic, downstream reports). It works - and it surfaces a gap: if the work lives in chat, we don’t get lineage, DQ, standardization, or a corpus leaders can query.

I’d like 90 days to pilot **fathm** on this workflow: keep the agent as the draft surface, but require every publish to be a gated **analysis package** with queryable provenance (chart room for you / Curran / Ashwini / Gaia-style questions).

Success: agent-default drafts, 100% in-scope packages, weekly sponsor query. Expand / handoff / kill at day 90. Not an org-wide platform ask.

Happy to walk through in 25 minutes.

---

## Delivery notes (for Tom)

- Lead with **SSD proof** (you did the thing) - not brand mythology  
- Say **fathm** once; if name distracts, “analysis package pilot” is fine  
- Name leaders only if appropriate in your org culture; else “leadership can query”  
- Bring one ugly artifact: chat → final report with no lineage link  
- Offer kill criteria unprompted - builds trust  
- Clawbot: “channel mixed adoption,” not “everyone must use X”  

## Optional objection handles

| Pushback | Reply |
|----------|--------|
| “Just use our catalog / DQ tool” | Wrong grain - those are tables/pipelines; this is the **analysis publish** unit bots create. |
| “Agents aren’t ready” | Mixed adoption is already here; SSD loop shows the upside. We’re governing reality. |
| “More process slows us” | Gate is the minimum to call it published; draft stays as fast as chat. |
| “Are you building a startup?” | Internal pilot to make our team AI-native and auditable. |
| “Planners will hate it” | Overrides keep **credit**; less rebuild next cycle. |
