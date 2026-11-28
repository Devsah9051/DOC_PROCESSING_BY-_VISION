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
    """Write an audit entry through the append-only log (canonical store).

    governance_audit_log is now a VIEW over append_only_log; all new writes go here.
    """
    import json
    import time

    from app.log import append_log

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
        "created_at": time.time(),
    }
    try:
        append_log("GATE_DECISION", entry_payload["payload"])
    except Exception:
        # Fallback: try direct insert if append_log not yet initialised
        with pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO append_only_log (entry_hash, prev_hash, kind, version_id, payload_json, created_at, signature) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        "0" * 64,
                        "0" * 64,
                        "GATE_DECISION",
                        None,
                        json.dumps(entry_payload, sort_keys=True),
                        entry_payload["created_at"],
                        None,
                    ),
                )
            conn.commit()


# ---- version registry (Section 5.3) ----

def get_version(sha256: str, track: str) -> Optional[tuple[str, int]]:
    """Return (version_id, version_seq) if a version already exists for (sha256, track)."""
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT version_id, version_seq FROM version_registry "
                "WHERE sha256=%s AND track=%s ORDER BY version_seq DESC LIMIT 1",
                (sha256, track),
            )
            row = cur.fetchone()
            return (row[0], row[1]) if row else None


def register_version(sha256: str, track: str, owner: str, version_seq: int, outcome: str) -> bool:
    """Compare-and-swap register a new version. Returns True if we won the CAS."""
    version_id = f"{sha256[:16]}:v{version_seq}"
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO version_registry (version_id, sha256, track, version_seq, owner, outcome) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (sha256, track) DO NOTHING "
                "RETURNING version_id",
                (version_id, sha256, track, version_seq, owner, outcome),
            )
            row = cur.fetchone()
            conn.commit()
            return row is not None


# ---- transactional outbox (Section 5.3) ----

def outbox_insert(
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict,
    conn=None,
) -> int:
    """Insert an outbox entry. If conn is provided, uses that connection (enables same-transaction writes)."""
    import json

    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO outbox (aggregate_type, aggregate_id, event_type, payload) "
                "VALUES (%s,%s,%s,%s) RETURNING id",
                (aggregate_type, aggregate_id, event_type, json.dumps(payload)),
            )
            row = cur.fetchone()
            return row[0]
    with pool().connection() as c:
        with c.cursor() as cur:
            cur.execute(
                "INSERT INTO outbox (aggregate_type, aggregate_id, event_type, payload) "
                "VALUES (%s,%s,%s,%s) RETURNING id",
                (aggregate_type, aggregate_id, event_type, json.dumps(payload)),
            )
            row = cur.fetchone()
            c.commit()
            return row[0]


def outbox_claim_pending(limit: int = 10) -> list[dict]:
    """Claim pending outbox entries for processing. Returns claimed rows."""
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE outbox "
                "SET status = 'processing', attempts = attempts + 1 "
                "WHERE id IN ("
                "    SELECT id FROM outbox "
                "    WHERE status = 'pending' "
                "    ORDER BY created_at ASC "
                "    LIMIT %s FOR UPDATE SKIP LOCKED"
                ") "
                "RETURNING id, aggregate_type, aggregate_id, event_type, payload, attempts",
                (limit,),
            )
            rows = cur.fetchall()
            conn.commit()
            return [
                {
                    "id": r[0],
                    "aggregate_type": r[1],
                    "aggregate_id": r[2],
                    "event_type": r[3],
                    "payload": r[4] if isinstance(r[4], dict) else __import__("json").loads(r[4]),
                    "attempts": r[5],
                }
                for r in rows
            ]


def outbox_mark_done(outbox_id: int, result_payload: dict | None = None) -> None:
    """Mark an outbox entry as done, optionally storing a result payload."""
    import json

    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE outbox SET status = 'done', processed_at = NOW(), payload = COALESCE(%s::jsonb, payload) "
                "WHERE id = %s",
                (json.dumps(result_payload) if result_payload is not None else None, outbox_id),
            )
            conn.commit()


def outbox_mark_failed(outbox_id: int, error: str) -> None:
    """Mark an outbox entry as failed with an error message."""
    import json

    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE outbox SET status = 'failed', processed_at = NOW(), error = %s WHERE id = %s",
                (error, outbox_id),
            )
            conn.commit()


# ---- scan results ----

def scan_result_insert(sha256: str, file_type: str, scan_engine: str, infected: bool, threat_name: str | None, payload: dict | None = None) -> None:
    import json

    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO scan_results (sha256, file_type, scan_engine, infected, threat_name, payload) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (sha256) DO UPDATE SET "
                "  file_type = EXCLUDED.file_type, "
                "  scan_engine = EXCLUDED.scan_engine, "
                "  infected = EXCLUDED.infected, "
                "  threat_name = EXCLUDED.threat_name, "
                "  scanned_at = NOW(), "
                "  payload = EXCLUDED.payload",
                (sha256, file_type, scan_engine, infected, threat_name, json.dumps(payload) if payload else None),
            )
            conn.commit()


def scan_result_get(sha256: str) -> dict | None:
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sha256, file_type, scan_engine, infected, threat_name, scanned_at, payload "
                "FROM scan_results WHERE sha256 = %s",
                (sha256,),
            )
            row = cur.fetchone()
            if not row:
                return None
            import json
            return {
                "sha256": row[0],
                "file_type": row[1],
                "scan_engine": row[2],
                "infected": row[3],
                "threat_name": row[4],
                "scanned_at": row[5].isoformat() if row[5] else None,
                "payload": json.loads(row[6]) if row[6] else None,
            }


def scan_result_insert_full(
    sha256: str,
    file_type: str,
    original_size: int,
    sanitized_size: int,
    scan_engine: str,
    infected: bool,
    threat_name: str | None,
    findings: list[dict] | None = None,
    cdr_applied: bool = False,
    cdr_method: str | None = None,
    payload: dict | None = None,
) -> None:
    import json

    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO scan_results (sha256, file_type, scan_engine, infected, threat_name, payload) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (sha256) DO UPDATE SET "
                "  file_type = EXCLUDED.file_type, "
                "  scan_engine = EXCLUDED.scan_engine, "
                "  infected = EXCLUDED.infected, "
                "  threat_name = EXCLUDED.threat_name, "
                "  scanned_at = NOW(), "
                "  payload = EXCLUDED.payload",
                (
                    sha256,
                    file_type,
                    scan_engine,
                    infected,
                    threat_name,
                    json.dumps({
                        "original_size": original_size,
                        "sanitized_size": sanitized_size,
                        "findings": findings or [],
                        "cdr_applied": cdr_applied,
                        "cdr_method": cdr_method,
                        **(payload or {}),
                    }),
                ),
            )
            conn.commit()
