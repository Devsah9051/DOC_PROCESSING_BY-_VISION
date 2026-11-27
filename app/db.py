from __future__ import annotations

import os
from typing import Optional

from psycopg_pool import ConnectionPool

_pool: Optional[ConnectionPool] = None


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def seal_key() -> str:
    key = os.environ.get("SEAL_KEY")
    if not key:
        raise RuntimeError("SEAL_KEY is not set")
    return key


def create_pool(db_url: str | None = None, **kwargs) -> ConnectionPool:
    global _pool
    url = db_url or database_url()
    _pool = ConnectionPool(url, **kwargs)
    return _pool


def pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised. Call create_pool() in lifespan.")
    return _pool


# ---- queries ----

def cache_get(sha256: str, pipeline_version: str, rules_version: str):
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT output_json FROM resume_cache "
                "WHERE sha256=%s AND pipeline_version=%s AND rules_version=%s",
                (sha256, pipeline_version, rules_version),
            )
            row = cur.fetchone()
            return row[0] if row else None


def cache_insert(sha256: str, pipeline_version: str, rules_version: str, output_json: str):
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO resume_cache (sha256, pipeline_version, rules_version, output_json) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (sha256, pipeline_version, rules_version, output_json),
            )
            conn.commit()


def audit_insert(upload_id: str, sha256: str, status: str, rules: list, quarantine_payload: str | None):
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO governance_audit_log (upload_id, sha256, status, rules, quarantine_payload) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (upload_id) DO NOTHING",
                (upload_id, sha256, status, rules, quarantine_payload),
            )
            conn.commit()
