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
