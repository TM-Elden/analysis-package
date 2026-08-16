"""`python3 -m ap_planner_bot.sweep`: the C6 sweep entry point (design report section 5.1/P4.4).

Runs the P4.2 corpus scan + detectors (already merged: `scan.py` / `detectors.py`), drafts
proposals for the resulting findings via `service.py`, and persists survivors through
`ap_proposals.ProposalWorkflow`. `run_sweep` is the plain library function both callers use:

- **Weekly systemd timer** (`fathm-planner-sweep.service` + `.timer` under `deploy/systemd/`,
  mirroring the `fathm-chat-telegram.service` precedent) invokes `main()`, which resolves
  identity from `AP_ACTOR_ID`/`AP_ACTOR_ROLES` (`ap_auth.identity.identity_from_env` - the
  established same-machine path, same as `ap-store`/`ap-gate` CLIs) and the same
  `AP_STORE_ROOT`/`AP_INDEX_ROOT` env-var convention `ap_api.deps` uses (resolved independently
  here rather than importing `ap_api` - a sweep entry point is a peer of the interface layer, not
  a consumer of it).
- **Console "Run planner sweep" button** (`ap_console.routes.standard_sweep`) calls `run_sweep`
  directly in-request under the triggering session's own identity, not a service identity - a full
  scan is seconds at pilot scale (report section 5.2), so no background job is needed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from ap_auth.identity import Identity, identity_from_env
from ap_index.index_store import IndexStore
from ap_manager_bot.llm_client import AnthropicHTTPClient
from ap_planner_bot.detectors import run_all_detectors
from ap_planner_bot.scan import scan_corpus
from ap_planner_bot.service import SweepDraftResult, draft_proposals
from ap_proposals.policy import ProposalPolicy
from ap_proposals.store import ProposalStore
from ap_proposals.workflow import ProposalWorkflow
from ap_store.store import PackageStore

#: Same local-first default/override convention as ap_api.deps.DEFAULT_STORE_ROOT/DEFAULT_INDEX_ROOT
#: - resolved independently here (not imported from ap_api) so this entry point has no dependency
#: on the interface layer; see module docstring.
DEFAULT_STORE_ROOT = Path(os.environ.get("AP_STORE_ROOT", str(Path.home() / ".fathm" / "ap_store")))
DEFAULT_INDEX_ROOT = Path(os.environ.get("AP_INDEX_ROOT", str(Path.home() / ".fathm" / "ap_index")))


def run_sweep(
    *,
    store: PackageStore,
    index: IndexStore,
    proposal_store: ProposalStore,
    llm_client: AnthropicHTTPClient,
    identity: Identity,
) -> SweepDraftResult:
    """Scan -> detect -> draft -> persist, over the stores/client given. Pure library call - no
    env resolution, no process I/O - so `main()` and tests (and the console route) share exactly
    this one code path."""
    scan = scan_corpus(store)
    findings = run_all_detectors(scan)
    workflow = ProposalWorkflow(store=proposal_store, policy=ProposalPolicy())
    return draft_proposals(findings, index=index, workflow=workflow, llm_client=llm_client, identity=identity)


def main() -> None:
    identity = identity_from_env()
    store = PackageStore(DEFAULT_STORE_ROOT)
    index = IndexStore(DEFAULT_INDEX_ROOT)
    proposal_store = ProposalStore(DEFAULT_STORE_ROOT)
    with AnthropicHTTPClient() as llm_client:
        result = run_sweep(
            store=store, index=index, proposal_store=proposal_store, llm_client=llm_client, identity=identity
        )
    discarded = ", ".join(f"{reason}={count}" for reason, count in sorted(result.discarded.items()))
    print(
        f"fathm-p4-sweep: {len(result.created)} proposal(s) created"
        + (f" (discarded: {discarded})" if discarded else ""),
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
