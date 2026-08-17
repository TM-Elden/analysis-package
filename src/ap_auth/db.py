"""SQLite schema for the C11 auth store (`users` + `sessions`).

Deliberately a **sibling** database (`auth.sqlite3`), not tables bolted onto `ap_store`'s
`index.sqlite3`: identity/credentials and package metadata are different lifecycles and different
blast radii (a leaked auth DB is a credential incident; a leaked package index is not), and keeping
them in separate files means `ap_store.PackageStore` never needs to know auth exists. See
`ap_auth.store.AuthStore` for the connection/locking pattern, which mirrors
`ap_store.db.connect`/`PackageStore` exactly (one `check_same_thread=False` connection guarded by an
`RLock`, because `ap_api`'s FastAPI sync handlers run in threadpool worker threads).

Single-tenant, same as `ap_store` (see CLAUDE.md) - no `tenant_id` column here either.

`sessions` holds both browser sessions and service-account bearer tokens (`kind` distinguishes them
for admin/audit display only; validation treats both the same - see `AuthStore.identity_for_token`).
Only the sha256 hash of the opaque token is ever stored, never the raw token - the raw token exists
only in the HTTP response at issuance time and in the caller's hands after that.

`auth_audit` (P5.3) records every admin-driven credential mutation (role change, password reset,
disable/enable, token issue/revoke) - who did it, to whom, when - the same "no mutation without an
audit row" standard `ap_store.db`'s `package_audit` already sets. `actor_id`/`actor_roles` are
nullable because the `ap-auth` CLI bootstrap path (no HTTP identity) still writes rows with a null
actor rather than skip auditing entirely - see `AuthStore`'s `actor: Identity | None` parameters.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    password_hash TEXT,
    roles TEXT NOT NULL,
    disabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    revoked INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS auth_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id TEXT,
    actor_roles TEXT,
    target_user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_audit_target ON auth_audit(target_user_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
