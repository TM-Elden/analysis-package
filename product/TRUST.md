# Trust stance

**Status:** Decided for product and pilot conversations.

## Commitments

1. **No cross-customer content training.** We do not train foundation or multi-tenant models on a customer's underlying business numbers, narratives, or file contents for resale or reuse by other customers.

2. **Structure / conformance only for pooled learning.** Any cross-customer learning is limited to structure and conformance behavior - e.g. which gate checks fail, reason_code distributions, schema fix patterns - never raw package payloads.

3. **Per-customer isolation for Team Models.** Team Model / RAG indices are single-tenant to that customer's instance and corpus.

4. **Opt-in training eligibility inside a tenant.** Packages default to `training_eligibility: false`. Enabling training on package contents for *that customer's own* Team Model requires explicit policy + package flag.

5. **Customer can export and leave.** Packages are portable directories/crates. Exit does not require our SaaS to read historical work.

## Exceptions

- **Inference-time LLM egress (C4 manager bot).** Retrieved, redacted, in-scope package content may be
  sent to a frontier-model API (Anthropic) at query time, under that provider's no-training API terms,
  to answer a caller's question. This is a deliberate exception distinct from - and not in conflict
  with - the training/pooling commitments above: no content is used to train or fine-tune a model, and
  nothing is pooled across customers. Resolved captain decision
  `fathm-phase3-readiness-decision-llm-egress-posture` (2026-08-16). See `AGENTS.md`'s Phase 3 manager-bot
  section for the implementation (`src/ap_manager_bot/llm_client.py`).

## Why this is non-negotiable

Selling Standard + CI into finance/ops only works if two competitors in the same industry can both buy without fearing leakage into each other's models.

## Implementation notes (later)

- Contractual language in MSA/DPA  
- Technical controls: tenant isolation, separate indices, no raw payload in shared telemetry  
- Gate metrics pipelines scrub content by default  
