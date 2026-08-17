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
from ap_chat.telegram.notify import notifier_from_env
from ap_index.index_store import IndexStore
from ap_manager_bot.llm_client import AnthropicHTTPClient
from ap_planner_bot.analytics import build_snapshot, compute_corpus_analytics
from ap_planner_bot.detectors import run_all_detectors
from ap_planner_bot.scan import scan_corpus
from ap_planner_bot.service import SweepDraftResult, draft_proposals
from ap_planner_bot.snapshot_store import append_snapshot
from ap_proposals.notify import ProposalNotifier
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
    notifier: ProposalNotifier | None = None,
) -> SweepDraftResult:
    """Scan -> detect -> draft -> persist, over the stores/client given. Pure library call, though
    not I/O-free: this is also the P5.2 trend recorder, so it appends one gate-analytics snapshot
    row (`ap_planner_bot.analytics.build_snapshot`, no person identifiers - see that module's
    docstring) to `<store.root>/analytics/snapshots.jsonl` on every call, sweep or console
    "Recompute now" button alike, using the same scan this function already ran - no second scan.
    `main()` and tests (and the console route) all share exactly this one code path. `notifier`
    (§5.8, default `None` = no notifications) fires `proposal.created` for each proposal
    `draft_proposals` persists - see `ap_proposals.notify`."""
    scan = scan_corpus(store)
    append_snapshot(store.root, build_snapshot(compute_corpus_analytics(scan)))
    findings = run_all_detectors(scan)
    workflow = ProposalWorkflow(store=proposal_store, policy=ProposalPolicy(), notifier=notifier)
    return draft_proposals(findings, index=index, workflow=workflow, llm_client=llm_client, identity=identity)


def main() -> None:
    identity = identity_from_env()
    store = PackageStore(DEFAULT_STORE_ROOT)
    index = IndexStore(DEFAULT_INDEX_ROOT)
    proposal_store = ProposalStore(DEFAULT_STORE_ROOT)
    notifier = notifier_from_env()
    with AnthropicHTTPClient() as llm_client:
        result = run_sweep(
            store=store,
            index=index,
            proposal_store=proposal_store,
            llm_client=llm_client,
            identity=identity,
            notifier=notifier,
        )
    discarded = ", ".join(f"{reason}={count}" for reason, count in sorted(result.discarded.items()))
    print(
        f"fathm-p4-sweep: {len(result.created)} proposal(s) created"
        + (f" (discarded: {discarded})" if discarded else ""),
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
