"""SQLite schema for the package store index (C3).

Single-tenant by design: no `tenant_id` column anywhere in this schema. Packages themselves never
carry a `tenant_id` field either (established in phase 1 - see CLAUDE.md). If multi-tenancy is ever
needed it is a store-level concept layered on top of this module (e.g. one `PackageStore` root per
tenant), not a column threaded through every query here - see CLAUDE.md for the explicit rationale.

`packages` rows are one per immutable `(package_id, package_version)` pair - see ap_store.store for
the immutability contract. `status` is the one mutable column: it is the review/lifecycle workflow's
current state (ap_review's draft/in_review/approved/rejected, plus ap_lifecycle's
superseded/recalled/purged layered on top - see CLAUDE.md's Phase 5 section), tracked separately
from whatever `qa.status` the immutable manifest bytes happened to declare at publish time (mirrors
the existing ap_gate precedent that a package's manifest-declared qa.checks[] is historical, not the
live source of truth - see CLAUDE.md).

`store_settings` (P5.3) is a small audited tenant/store-level config KV table - it lives here, not
in `auth.sqlite3`, because store/tenant configuration (e.g. `retention_days`, read by the C12
lifecycle task) is a different domain than credentials (see `ap_auth.db`'s own "wrong home"
reasoning in reverse). Every write is mirrored into `store_settings_audit` (old value, new value,
actor, when) by `PackageStore.set_setting` - same "no mutation without an audit row" standard as
`package_audit`.

`legal_hold` / `legal_hold_reason` / `purged_at` on `packages` (C12, ap_lifecycle) are the lifecycle
columns: hold blocks purge only (recall/supersede stay allowed under hold - see ap_lifecycle);
`purged_at` marks the first genuinely irreversible operation in the product (see
`PackageStore.purge`).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS packages (
    package_id TEXT NOT NULL,
    package_version TEXT NOT NULL,
    profile TEXT NOT NULL,
    title TEXT NOT NULL,
    as_of TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    blob_sha256 TEXT NOT NULL,
    analyst_id TEXT,
    reviewer_id TEXT,
    owners_json TEXT NOT NULL,
    gate_overall TEXT NOT NULL,
    published_by_id TEXT NOT NULL,
    published_by_roles TEXT NOT NULL,
    replaces_package_id TEXT,
    replaces_package_version TEXT,
    legal_hold INTEGER NOT NULL DEFAULT 0,
    legal_hold_reason TEXT,
    purged_at TEXT,
    PRIMARY KEY (package_id, package_version)
);

CREATE TABLE IF NOT EXISTS package_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package_id TEXT NOT NULL,
    package_version TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_roles TEXT NOT NULL,
    reason TEXT,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS store_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by_id TEXT,
    updated_by_roles TEXT
);

CREATE TABLE IF NOT EXISTS store_settings_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT NOT NULL,
    actor_id TEXT,
    actor_roles TEXT,
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_packages_status ON packages(status);
CREATE INDEX IF NOT EXISTS idx_packages_profile ON packages(profile);
CREATE INDEX IF NOT EXISTS idx_packages_as_of ON packages(as_of);
CREATE INDEX IF NOT EXISTS idx_audit_package ON package_audit(package_id, package_version);
CREATE INDEX IF NOT EXISTS idx_settings_audit_key ON store_settings_audit(key);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the index DB. `check_same_thread=False` because ap_api's FastAPI sync route handlers
    run each request in a threadpool worker thread, not the thread PackageStore was constructed on
    - PackageStore serializes all access with its own lock (see ap_store.store), so this is safe.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
