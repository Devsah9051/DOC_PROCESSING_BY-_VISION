from __future__ import annotations

from typing import Any, Optional

from app import db
from app.hash import log_hash


LOG_ENTRY_KINDS = {
    "GATE_DECISION",
    "SEAL",
    "FILE_STATE_UPDATE",
    "HUMAN_DECISION",
    "TOMBSTONE",
    "CHECKPOINT",
}


def _ensure_log_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS append_only_log (
                id BIGSERIAL PRIMARY KEY,
                entry_hash TEXT NOT NULL UNIQUE,
                prev_hash TEXT NOT NULL,
                kind TEXT NOT NULL,
                version_id TEXT,
                payload_json TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                signature TEXT
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_append_only_log_kind ON append_only_log(kind)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_append_only_log_version ON append_only_log(version_id)"
        )


def _get_last_hash(conn) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT entry_hash FROM append_only_log ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        return row[0] if row else "0" * 64


def append_log(
    kind: str,
    payload: dict[str, Any],
    version_id: Optional[str] = None,
    signature: Optional[str] = None,
) -> str:
    """Append an entry to the append-only log. Returns the entry hash.

    Each entry is hashed with egca/log/v1 and chained to the previous entry.
    One writer at a time (PostgreSQL advisory transaction lock ensures serialisation).
    """
    if kind not in LOG_ENTRY_KINDS:
        raise ValueError(f"invalid log entry kind: {kind}")

    import time
    import json
    from datetime import datetime, timezone

    with db.pool().connection() as conn:
        with conn.cursor() as cur:
            # Single-writer guard: advisory transaction lock
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('egca_log'))")
            _ensure_log_table(conn)
            prev_hash = _get_last_hash(conn)
            created_at = datetime.now(timezone.utc)
            entry_payload = {
                "kind": kind,
                "version_id": version_id,
                "payload": payload,
                "created_at": created_at.isoformat(),
            }
            entry_hash = log_hash(entry_payload)
            cur.execute(
                """
                INSERT INTO append_only_log
                    (entry_hash, prev_hash, kind, version_id, payload_json, created_at, signature)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    entry_hash,
                    prev_hash,
                    kind,
                    version_id,
                    json.dumps(entry_payload, sort_keys=True),
                    created_at,
                    signature,
                ),
            )
        conn.commit()
        return entry_hash


def get_log_chain(limit: int = 100) -> list[dict[str, Any]]:
    """Return the most recent log entries, newest first."""
    import json

    with db.pool().connection() as conn:
        with conn.cursor() as cur:
            _ensure_log_table(conn)
            cur.execute(
                """
                SELECT entry_hash, prev_hash, kind, version_id, payload_json, created_at, signature
                FROM append_only_log
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    return [
        {
            "entry_hash": r[0],
            "prev_hash": r[1],
            "kind": r[2],
            "version_id": r[3],
            "payload": json.loads(r[4]),
            "created_at": r[5].isoformat() if r[5] else None,
            "signature": r[6],
        }
        for r in rows
    ]


def verify_chain() -> bool:
    """Verify the log chain is intact: each entry's hash recomputes and chains to prev."""
    import json

    with db.pool().connection() as conn:
        with conn.cursor() as cur:
            _ensure_log_table(conn)
            cur.execute(
                "SELECT entry_hash, prev_hash FROM append_only_log ORDER BY id ASC"
            )
            rows = cur.fetchall()
    prev = "0" * 64
    for entry_hash, prev_hash_db in rows:
        if prev_hash_db != prev:
            return False
        # payload_json IS the serialized entry_payload that was hashed in append_log
        with db.pool().connection() as conn2:
            with conn2.cursor() as cur2:
                cur2.execute(
                    "SELECT payload_json FROM append_only_log WHERE entry_hash = %s",
                    (entry_hash,),
                )
                row = cur2.fetchone()
        entry = json.loads(row[0])
        expected = log_hash(entry)
        if expected != entry_hash:
            return False
        prev = entry_hash
    return True
