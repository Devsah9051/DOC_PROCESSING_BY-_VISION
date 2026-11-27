from __future__ import annotations

import os
import sys

import psycopg

SCHEMA = """
CREATE TABLE IF NOT EXISTS resume_cache (
    sha256 TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    output_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (sha256, pipeline_version, rules_version)
);

CREATE TABLE IF NOT EXISTS governance_audit_log (
    upload_id TEXT UNIQUE NOT NULL,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    rules JSONB NOT NULL DEFAULT '[]'::jsonb,
    quarantine_payload JSONB,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS version_registry (
    version_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    track TEXT NOT NULL,
    version_seq INTEGER NOT NULL,
    owner TEXT NOT NULL,
    outcome TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (sha256, track)
);

-- Transactional outbox for reliable event publishing (Section 5.3).
-- Business data and outbox entries are written in the same transaction;
-- a scanner daemon polls pending entries and publishes them.
CREATE TABLE IF NOT EXISTS outbox (
    id SERIAL PRIMARY KEY,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status);
CREATE INDEX IF NOT EXISTS idx_outbox_aggregate ON outbox(aggregate_type, aggregate_id);

-- Malware scan results keyed by file sha256 (Section 5.2).
-- Extended scan data (original_size, sanitized_size, findings, cdr_applied, cdr_method)
-- is stored in the payload JSONB column.
CREATE TABLE IF NOT EXISTS scan_results (
    sha256 TEXT PRIMARY KEY,
    file_type TEXT NOT NULL,
    scan_engine TEXT NOT NULL,
    infected BOOLEAN NOT NULL,
    threat_name TEXT,
    scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB
);

-- TTL cleanup: resumes are personal data. Rows older than the retention
-- window are removed by a periodic job (see cleanup_ttl()). No built-in
-- TTL in Postgres, so this is run on a schedule.
"""


def init_db(database_url: str | None = None):
    url = database_url or os.environ["DATABASE_URL"]
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
        conn.commit()
    print("Database initialized: resume_cache, governance_audit_log")


def cleanup_ttl(retention_days: int = 30, database_url: str | None = None):
    """Remove personal data older than retention_days from the audit log."""
    url = database_url or os.environ["DATABASE_URL"]
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM governance_audit_log WHERE ts < NOW() - (%s || ' days')::interval",
                (str(retention_days),),
            )
            deleted = cur.rowcount
        conn.commit()
    print(f"TTL cleanup: deleted {deleted} audit rows older than {retention_days} days")


if __name__ == "__main__":
    if "--cleanup" in sys.argv:
        cleanup_ttl()
    else:
        init_db()
