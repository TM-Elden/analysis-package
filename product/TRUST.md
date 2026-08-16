# Trust stance

**Status:** Decided for product and pilot conversations.

## Commitments

1. **No cross-customer content training.** We do not train foundation or multi-tenant models on a customer's underlying business numbers, narratives, or file contents for resale or reuse by other customers.

2. **Structure / conformance only for pooled learning.** Any cross-customer learning is limited to structure and conformance behavior - e.g. which gate checks fail, reason_code distributions, schema fix patterns - never raw package payloads.

3. **Per-customer isolation for Team Models.** Team Model / RAG indices are single-tenant to that customer's instance and corpus.

4. **Opt-in training eligibility inside a tenant.** Packages default to `training_eligibility: false`. Enabling training on package contents for *that customer's own* Team Model requires explicit policy + package flag.

5. **Customer can export and leave.** Packages are portable directories/crates. Exit does not require our SaaS to read historical work.

## Why this is non-negotiable

Selling Standard + CI into finance/ops only works if two competitors in the same industry can both buy without fearing leakage into each other's models.

## Implementation notes (later)

- Contractual language in MSA/DPA  
- Technical controls: tenant isolation, separate indices, no raw payload in shared telemetry  
- Gate metrics pipelines scrub content by default  
