# Stage 3: Govern — Checkpoint Log

## Overview
**File:** `stages/s3_govern.py`
**Pipeline Role:** Governance — pre-gate/post-gate decisions, suspicion rating, file state.
**Dependents:** `app/pipeline.py` govern_pre/govern_post calls.

---

## Purpose
- Pre-gate (before parsing): idempotency key, epoch fencing, state watcher, cache check
- Post-gate (after Stage 2): universal injection scan, suspicion rating, file state
- Return proceed flag and reason

---

## Current State

### Code Structure
```python
def govern_pre(upload_id, sha256, config) -> dict:
    # Pre-gate: idempotency, cache, state watcher
    return {"proceed": bool, "reason": str}

def govern_post(upload_id, sha256, verdict, quarantine_payload=None) -> dict:
    # Post-gate: universal scan, suspicion rating, file state
    return {"proceed": bool, "reason": str, "file_state": FileState | None}

def compute_suspicion(findings) -> tuple[float, str, list[str]]:
    # Suspicion rating from finding weights
    return (total, tier, rule_ids)
```

### Key Functions
- `govern_pre()` — pre-gate decision
- `govern_post()` — post-gate decision
- `compute_suspicion()` — weighted suspicion rating
- `latest_version_ok()` — stub (STUB)
- `job_open_ok()` — stub (STUB)

---

## Applied Patches
None directly — this file was substantially rewritten for spec alignment:
- Pre-gate/post-gate split
- Suspicion rating with severity weights
- File state computation (risk_tier, suspicion_status, parse_status, findings, warnings)
- Append-only log entries (GATE_DECISION)

---

## Configuration Dependencies
| Setting | Default | Used In |
|---------|---------|---------|
| `suspicious_score` | 5.0 | Review threshold |
| `weights` | various | Suspicion rating |

---

## Test Coverage
**File:** `tests/test_s3_govern.py`
| Test | Function | Status |
|------|----------|--------|
| `test_govern_pre_clean_proceeds` | govern_pre() | PASS |
| `test_govern_post_clean_proceeds` | govern_post() CLEAN | PASS |
| `test_govern_post_quarantine_stops` | govern_post() QUARANTINE | PASS |

---

## Known Issues & Remaining Tasks

| Issue | Severity | Details | Fix Needed |
|-------|----------|---------|------------|
| Stub: latest-version check | LOW | Always returns True | Wire to external service (spec 4.2) |
| Stub: job-open check | LOW | Always returns True | Wire to external service (spec 4.3) |
| Pre-gate idempotency | PARTIAL | idem_hash exists but not wired | Connect to cache |
| State watcher | STUB | JOB_CLOSED/APPLICATION_WITHDRAWN not implemented | Wire to external service |

### Spec Gaps (Section 7)
| Spec Ref | Requirement | Current State | Gap |
|----------|-------------|---------------|-----|
| 7.1 | Decide twice: pre-gate + post-gate | Implemented | OK |
| 7.2 Pre-gate | Idempotency key | Implemented (idem_hash) | OK |
| 7.2 Pre-gate | Epoch fencing | NOT implemented | MISSING |
| 7.2 Pre-gate | State watcher | NOT implemented | MISSING |
| 7.2 Pre-gate | Result cache | PARTIAL | cache_get exists but not keyed per spec |
| 7.2 Post-gate | State watcher | NOT implemented | MISSING |
| 7.2 Post-gate | Universal injection scan | Implemented | OK |
| 7.2 Post-gate | Suspicion rating | Implemented | OK |
| 7.2 Post-gate | Early stop | Implemented | OK |
| 7.2 Post-gate | Near-duplicate check | NOT implemented | MISSING |
| 7.2 Post-gate | Audit GATE_DECISION | Implemented | OK |
| 7.3 | Universal scan: visible + hidden + side channel | Partial | Side channel not separate |
| 7.4 | Finding weights | Implemented | OK |
| 7.4 | Start-up weight check | NOT implemented | MISSING |
| 7.4 | Informational flags weigh 0 | Implemented | OK |
| 7.4 | One finding per region type, capped | NOT implemented | MISSING |
| 7.4 | CLEAN/REVIEW/QUARANTINE thresholds | Implemented | OK |
| 7.4 | M2-M5 can lift CLEAN to REVIEW but never QUARANTINE | NOT implemented | MISSING |

---

## Next Steps
1. Wire `latest_version_ok()` to external version-check service
2. Wire `job_open_ok()` to external job-open check service
3. Implement state watcher for job closed/application withdrawn
4. Implement near-duplicate check

---

## Relevant File Links
- `stages/s3_govern.py` — Stage 3 implementation
- `app/db.py` — `audit_insert()` for governance audit log
- `app/log.py` — append-only log with GATE_DECISION entries
- `app/schemas.py` — FileState, Finding models
- `app/pipeline.py` — calls govern_pre/govern_post
- `tests/test_s3_govern.py` — unit tests
- `README.md` — Limitations section mentions stubs

---

## Checkpoint Status
**Status:** OPERATIONAL (stubs in place as designed)
**Last Verified:** 2026-11-27 — All 3 tests pass
**Next Review:** When external services for pre-gate/post-gate are specified
