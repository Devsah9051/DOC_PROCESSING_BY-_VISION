from __future__ import annotations

import os
import json

import pytest

from app import db
from app.log import append_log, get_log_chain, verify_chain, _ensure_log_table


@pytest.fixture
def db_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set; skipping Postgres-backed log tests")
    return url


@pytest.fixture(autouse=True)
def real_db_pool(db_url, monkeypatch):
    """Override the stubbed DB pool with a real PostgreSQL pool for log tests."""
    try:
        db.create_pool(db_url)
    except Exception:
        pytest.skip("PostgreSQL not available; skipping log chain tests")
    monkeypatch.setattr(db, "pool", lambda: db._pool)
    try:
        with db.pool().connection() as conn:
            _ensure_log_table(conn)
            conn.commit()
    except Exception:
        pytest.skip("PostgreSQL not available; skipping log chain tests")


def test_append_log_creates_chain(db_url):
    """Append entries and verify the chain is intact."""
    h1 = append_log("GATE_DECISION", {"upload_id": "u1", "sha256": "abc", "status": "CLEAN", "rules": []}, version_id="v1")
    h2 = append_log("GATE_DECISION", {"upload_id": "u2", "sha256": "def", "status": "REVIEW", "rules": ["R1"]}, version_id="v2")
    h3 = append_log("SEAL", {"stage5_root": "root", "file_state_hash": "fsh"}, version_id="v3")

    assert h1 != h2 != h3
    assert h1 and h2 and h3

    chain = get_log_chain(limit=10)
    assert len(chain) >= 3

    # Verify chain order (newest first)
    assert chain[0]["entry_hash"] == h3
    assert chain[1]["entry_hash"] == h2
    assert chain[2]["entry_hash"] == h1

    # Verify each entry chains to previous
    assert chain[0]["prev_hash"] == h2
    assert chain[1]["prev_hash"] == h1


def test_verify_chain_returns_true(db_url):
    """verify_chain() returns True for a valid, un-tampered chain."""
    append_log("GATE_DECISION", {"upload_id": "u1", "sha256": "abc", "status": "CLEAN", "rules": []}, version_id="v1")
    append_log("GATE_DECISION", {"upload_id": "u2", "sha256": "def", "status": "REVIEW", "rules": ["R1"]}, version_id="v2")

    assert verify_chain() is True


def test_verify_chain_detects_tampering(db_url):
    """verify_chain() returns False if an entry's hash is tampered with."""
    h1 = append_log("GATE_DECISION", {"upload_id": "u1", "sha256": "abc", "status": "CLEAN", "rules": []}, version_id="v1")
    h2 = append_log("GATE_DECISION", {"upload_id": "u2", "sha256": "def", "status": "REVIEW", "rules": ["R1"]}, version_id="v2")

    # Tamper: modify the payload of the first entry
    with db.pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE append_only_log SET payload_json = %s WHERE entry_hash = %s",
                (json.dumps({"tampered": True}, sort_keys=True), h1),
            )
        conn.commit()

    assert verify_chain() is False
