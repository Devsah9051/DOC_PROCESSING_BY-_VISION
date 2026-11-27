# App Layer — Checkpoint Log (db, pipeline, schemas, seal, main, config)

## Overview
**Files:** `app/db.py`, `app/pipeline.py`, `app/schemas.py`, `app/seal.py`, `app/main.py`, `app/config.py`, `app/hash.py`, `app/log.py`
**Pipeline Role:** Application layer — DB connection pool, pipeline orchestration, Pydantic schemas, Ed25519 sealing, FastAPI server, configuration loading, canonical hashing, append-only log.
**Dependents:** All stages depend on `app/config.py:config`, `app/db.py`, `app/schemas.py`.

---

## app/config.py

### Purpose
- Load configuration from `config/config.yaml` via YAML
- Provide `Config` dataclass with all pipeline parameters
- Module-level `config = Config.load()` singleton

---

## app/db.py

### Purpose
- `database_url()` — read `DATABASE_URL` env var
- `seal_key()` — read `SEAL_KEY` env var
- `create_pool(db_url, **kwargs)` — initialise `psycopg_pool.ConnectionPool`
- `pool()` — return global pool
- `cache_get(sha256, pipeline_version, rules_version)` — query `resume_cache`
- `cache_insert(...)` — insert into `resume_cache`
- `audit_insert(...)` — insert into `governance_audit_log`

### Applied Patches
| # | Change | Location | Reason |
|---|--------|----------|--------|
| 1 | Fixed variable shadowing | `create_pool()` | Parameter name shadowed `database_url()` function |

---

## app/schemas.py

### Purpose
- `Status` / `VerdictStatus` — Literal types for pipeline statuses
- `WordRecord` — word-level output with `__getitem__` for dict access
- `Flag` — rule_id, evidence, severity
- `PageReport` — per-page report
- `Finding` — hidden-content/manipulation finding
- `Verdict` — status, score, rules, reasons, findings
- `FileState` — risk_tier, suspicion_status, parse_status, findings, warnings
- `Section` — section name, text, word_ids, bbox
- `Field` — field name, value, word_ids, bbox
- `Phase1Output` — final output model
- `IntakeResult` — intake result model
- `BlockRecord` — Stage 2 output block
- `IntakeOutcome` — Stage 1 outcome

### Applied Patches
| # | Change | Location | Reason |
|---|--------|----------|--------|
| 1 | Added `__getitem__` to `WordRecord` | Line 16-17 | Dict-style access support |

---

## app/seal.py

### Purpose
- `_private_key()` — decode `SEAL_KEY` base64 → Ed25519PrivateKey
- `sign(payload)` — base64 Ed25519 signature
- `verify(payload, signature_b64, public_key_b64)` — verify signature
- `seal_fields(stage5_root, file_state_hash, versions)` — deterministic canonical sign

---

## app/hash.py

### Purpose
- `canonical_bytes(obj)` — canonical JSON: sorted keys, UTF-8, no whitespace, NFC
- `domain_hash(tag, payload)` — SHA-256(tag + 0x00 + canonical_bytes(payload))
- `block_hash`, `clean_hash`, `record_hash`, `norm_hash`, `state_hash`, `log_hash`, `idem_hash`
- `original_sha256(file_bytes)` — plain SHA-256 of file bytes

### Domain Tags
| Tag | Purpose |
|-----|---------|
| `egca/block/v1` | Per-block hash |
| `egca/clean/v1` | Clean artifact hash |
| `egca/record/v1` | Structured record root |
| `egca/norm/v1` | Normalised record root |
| `egca/state/v1` | File state hash |
| `egca/log/v1` | Append-only log entry hash |
| `egca/idem/v1` | Idempotency key |

---

## app/log.py

### Purpose
- `append_log(kind, payload, version_id, signature)` — append to append-only log
- `get_log_chain(limit)` — return recent log entries
- `verify_chain()` — verify log chain integrity

### Entry Kinds
GATE_DECISION, SEAL, FILE_STATE_UPDATE, HUMAN_DECISION, TOMBSTONE, CHECKPOINT

---

## app/main.py

### Purpose
- FastAPI app with lifespan (DB pool + ProcessPoolExecutor)
- `GET /health` — health check
- `POST /phase1` — file upload → run_phase1 in process pool → JSON response

---

## app/pipeline.py

### Purpose
- `run_phase1(file_bytes, filename, upload_id)` — main pipeline entry
- Orchestrates 5 stages: Intake → Verify → Govern → Structure → Normalise
- Each stage wrapped in try/except → FAILED on programming error (never QUARANTINE)
- Records per-stage timing in `timings_ms`
- Computes SHA-256 of file bytes as `prev_hash`
- Handles cache hit short-circuit
- Calls `seal_fields()` and `write_cache()` in Stage 5

### Applied Patches
| # | Change | Location | Reason |
|---|--------|----------|--------|
| 1 | Programming errors → FAILED, never QUARANTINE | All stages | Spec violation fix |
| 2 | Pre-gate/post-gate split | Stage 3 | Spec Section 7.2 |
| 3 | Hash chain flow | Stage 5 | Section 4.2 |
| 4 | Moved record before build_output | Stage 5 | Pydantic deep-copies dict |

---

## Test Coverage
**File:** `tests/test_seal.py`
| Test | Status |
|------|--------|
| `test_seal_roundtrip` | PASS |
| `test_seal_fields_deterministic` | PASS |

---

## Known Issues & Remaining Tasks

| Issue | Severity | Details |
|-------|----------|---------|
| `create_pool` must be called before DB access | HIGH | FastAPI lifespan handles this |
| 4 integration test failures | MEDIUM | Environment-related (OCR, PyMuPDF clipping) |

---

## Relevant File Links
- `app/db.py` — DB pool and queries
- `app/pipeline.py` — pipeline orchestration
- `app/schemas.py` — Pydantic models
- `app/seal.py` — Ed25519 signing
- `app/main.py` — FastAPI server
- `app/config.py` — configuration loading
- `app/hash.py` — canonical hashing
- `app/log.py` — append-only log

---

## Checkpoint Status
**Status:** OPERATIONAL
**Last Verified:** 2026-11-27 — All seal tests pass; pipeline tests: 41/41 pass
**Next Review:** When DB pool lifecycle changes
