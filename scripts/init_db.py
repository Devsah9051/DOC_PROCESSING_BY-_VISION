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

-- Canonical append-only audit log (Section 4.3).
-- All audit entries (governance decisions, seals, file state updates, human decisions,
-- tombstones, checkpoints) are written here. governance_audit_log is a VIEW over this
-- table for backward compatibility; no data is deleted.
CREATE TABLE IF NOT EXISTS append_only_log (
    id BIGSERIAL PRIMARY KEY,
    entry_hash TEXT NOT NULL UNIQUE,
    prev_hash TEXT NOT NULL,
    kind TEXT NOT NULL,
    version_id TEXT,
    payload_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    signature TEXT
);

CREATE INDEX IF NOT EXISTS idx_append_only_log_kind ON append_only_log(kind);
CREATE INDEX IF NOT EXISTS idx_append_only_log_version ON append_only_log(version_id);

-- Backward-compatible view over append_only_log.
-- governance_audit_log is now a VIEW so existing code that queries it still works,
-- but all new writes go through append_log() → append_only_log.
CREATE OR REPLACE VIEW governance_audit_log AS
SELECT
    id::TEXT AS upload_id,
    (payload_json::jsonb->>'sha256') AS sha256,
    kind AS status,
    (payload_json::jsonb->>'rules')::JSONB AS rules,
    (payload_json::jsonb->>'quarantine_payload')::JSONB AS quarantine_payload,
    created_at AS ts
FROM append_only_log
WHERE kind = 'GATE_DECISION';

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
    print("Database initialized: resume_cache, governance_audit_log, version_registry, outbox, scan_results, append_only_log")


def backfill_governance_audit_log(database_url: str | None = None):
    """One-time backfill: copy existing governance_audit_log rows into append_only_log
    before converting governance_audit_log to a VIEW."""
    url = database_url or os.environ["DATABASE_URL"]
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            # Check if old governance_audit_log table has rows (before we convert it to a view)
            cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'governance_audit_log' AND table_type = 'BASE TABLE'")
            if cur.fetchone()[0] == 0:
                # Table may already be a view; nothing to backfill
                conn.commit()
                return
            cur.execute(
                "SELECT upload_id, sha256, status, rules, quarantine_payload, ts FROM governance_audit_log"
            )
            rows = cur.fetchall()
            for upload_id, sha256, status, rules, quarantine_payload, ts in rows:
                import json
                import time
                from app.hash import log_hash
                entry_payload = {
                    "kind": "GATE_DECISION",
                    "version_id": None,
                    "payload": {
                        "upload_id": upload_id,
                        "sha256": sha256,
                        "status": status,
                        "rules": rules if rules else [],
                        "quarantine_payload": quarantine_payload,
                    },
                    "created_at": ts.timestamp() if hasattr(ts, "timestamp") else time.time(),
                }
                entry_hash = log_hash(entry_payload)
                cur.execute(
                    """
                    INSERT INTO append_only_log
                        (entry_hash, prev_hash, kind, version_id, payload_json, created_at, signature)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (entry_hash) DO NOTHING
                    """,
                    (
                        entry_hash,
                        "0" * 64,  # backfilled entries chain from genesis
                        "GATE_DECISION",
                        None,
                        json.dumps(entry_payload, sort_keys=True),
                        ts,
                        None,
                    ),
                )
        conn.commit()
    print(f"Backfilled {len(rows)} governance_audit_log rows into append_only_log")


def cleanup_ttl(retention_days: int = 30, database_url: str | None = None):
    """Remove personal data older than retention_days from the audit log."""
    url = database_url or os.environ["DATABASE_URL"]
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM append_only_log WHERE created_at < NOW() - (%s || ' days')::interval",
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
