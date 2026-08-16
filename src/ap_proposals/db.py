"""SQLite schema for the C6/C7 proposal store.

Sibling database (`<store_root>/proposals.sqlite3`), not new tables in `ap_store`'s
`index.sqlite3` - see `ap_proposals` module docstring and CLAUDE.md's `ap_proposals` section for the
full rationale. Same connect/RLock pattern as `ap_store.db` / `ap_auth.db`: one
`check_same_thread=False` connection guarded by an `RLock` in `ProposalStore`, since `ap_api`'s
FastAPI sync route handlers each run in their own threadpool worker thread.

`status` is the mutable workflow column (`pending_hitl -> approved | rejected | withdrawn`, see
`ap_proposals.workflow`); every other column is either set once at creation or once at decision
time. `edited_diff_json` is populated only for approve-with-edits and is stored *beside*
`diff_json`, never over it - the original proposed diff is never lost.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    rationale TEXT NOT NULL,
    diff_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_by_id TEXT NOT NULL,
    created_by_roles TEXT NOT NULL,
    decided_by_id TEXT,
    decided_at TEXT,
    decision_reason TEXT,
    edited_diff_json TEXT,
    dry_run_json TEXT,
    applied_version TEXT,
    applied_at TEXT
);

CREATE TABLE IF NOT EXISTS proposal_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_roles TEXT NOT NULL,
    reason TEXT,
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
CREATE INDEX IF NOT EXISTS idx_proposals_kind ON proposals(kind);
CREATE INDEX IF NOT EXISTS idx_proposal_audit_proposal ON proposal_audit(proposal_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the proposal DB. `check_same_thread=False` for the same reason as `ap_store.db.connect`
    and `ap_auth.db.connect`: FastAPI sync handlers run in threadpool worker threads, and
    `ProposalStore` serializes all access with its own `RLock` rather than relying on sqlite3's
    per-thread connection default.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
