"""SQLite connection + schema. Pure stdlib, zero-config.

The schema is intentionally Postgres-portable: TEXT/JSON columns, simple indexes,
no SQLite-only features. ``canonical_json`` would become ``JSONB`` in Postgres.
"""

from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidate (
    id                 TEXT PRIMARY KEY,
    canonical_json     TEXT,
    trust_json         TEXT,
    overall_confidence REAL,
    status             TEXT,   -- 'accepted' | 'needs_review' | 'reviewed'
    updated_at         TEXT
);

CREATE TABLE IF NOT EXISTS source_record (
    id           TEXT PRIMARY KEY,   -- content hash -> idempotent ingestion
    candidate_id TEXT NOT NULL,
    source       TEXT NOT NULL,
    raw_json     TEXT NOT NULL,
    methods_json TEXT NOT NULL,
    ingested_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_source_candidate ON source_record(candidate_id);

CREATE TABLE IF NOT EXISTS candidate_key (
    key_type     TEXT NOT NULL,
    key_value    TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    PRIMARY KEY (key_type, key_value, candidate_id)
);
CREATE INDEX IF NOT EXISTS ix_key_lookup ON candidate_key(key_type, key_value);

CREATE TABLE IF NOT EXISTS correction (
    candidate_id TEXT NOT NULL,
    field        TEXT NOT NULL,
    value        TEXT,
    created_at   TEXT,
    PRIMARY KEY (candidate_id, field)
);

-- Self-calibrating trust: how often each source's winning value was corrected.
CREATE TABLE IF NOT EXISTS source_stat (
    source    TEXT PRIMARY KEY,
    overrides INTEGER NOT NULL DEFAULT 0
);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    # check_same_thread=False: the Flask dev server serves requests on multiple
    # threads; we serialize writes with a lock in the Repository. timeout handles
    # the rare "database is locked" under contention.
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
