"""ap_proposals: C6/C7 Standard-change proposal storage, workflow, and JSON API.

Storage lives at `<store_root>/proposals.sqlite3`, a sibling database to `ap_store`'s
`index.sqlite3` and `ap_auth`'s `auth.sqlite3` - proposals are Standard-governance state, a
different domain with a different lifecycle than package metadata, exactly the same reasoning that
keeps `auth.sqlite3` separate (see `ap_auth.db`'s module docstring and CLAUDE.md). See
`ap_proposals.store.ProposalStore` for the connect/RLock pattern (mirrors `ap_store.PackageStore`
and `ap_auth.AuthStore`) and `ap_proposals.workflow.ProposalWorkflow` for the C7 policy/mechanism
split (mirrors `ap_review.ReviewWorkflow`).
"""

from __future__ import annotations
