# Stage 1: Intake — Checkpoint Log

## Overview
**File:** `stages/s1_intake.py`
**Pipeline Role:** Entry point for PDF uploads — validates file integrity, checks cache, opens document, enforces size/page/pixel limits.
**Dependents:** `app/pipeline.py:run_phase1()`, `app/db.py:cache_get()`

---

## Purpose
- Enforce max file size (10 MB default)
- Validate safe filename characters
- Verify `%PDF-` header magic bytes
- Compute SHA-256 of file bytes
- Check cache (sha256 + pipeline_version + rules_version)
- Open PDF with PyMuPDF; reject encrypted/corrupt documents
- Enforce max_pages (10) and max_pixels (50M per page at 150 DPI)
- Return `IntakeContext` with document handle for downstream stages

---

## Current State

### Code Structure
```python
@dataclass
class IntakeContext:
    sha256: str
    size_bytes: int
    filename: str
    page_count: int
    encrypted: bool
    cache_hit: bool
    cached_output: dict | None
    doc: object | None  # pymupdf Document
```

### Key Functions
- `sha256_of(data)` — SHA-256 hex digest
- `is_safe_filename(filename)` — regex `^[A-Za-z0-9._-]+$`
- `intake(file_bytes, filename, upload_id, cfg)` — main entry; raises `Stage1Error` on failure

---

## Applied Patches
None directly in this file. Patches in other files affect Stage 1 behavior:
- `app/db.py`: Fixed `database_url()` parameter shadowing (affects `cache_get` call)
- `app/schemas.py`: Added `WordRecord.__getitem__`

---

## Configuration Dependencies (`config/config.yaml`)
| Key | Default | Used In Stage 1 |
|-----|---------|-----------------|
| `max_bytes` | 10,000,000 | Size cap |
| `max_pages` | 10 | Page count limit |
| `max_pixels` | 50,000,000 | Per-page render pixel limit |
| `dpi` | 150 | Render DPI for pixel check |
| `pipeline_version` | "1.0.0" | Cache key |
| `rules_version` | "1.0.0" | Cache key |

---

## Test Coverage
**File:** `tests/test_pipeline.py` (integration)
- `test_cache_hit_returns_cached` — verifies cache returns `Phase1Output` from `cached_output`
- `test_corrupt_pdf_quarantined` — corrupt PDF → FAILED via Stage1Error
- `test_oversized_pdf_quarantined` — oversized page → FAILED via Stage1Error

**File:** `tests/conftest.py`
- `corrupt_pdf` fixture — b"%PDF-1.4\ncorrupt garbage..."
- `oversized_pdf` fixture — 10000x10000 page

---

## Known Issues & Remaining Tasks

| Issue | Severity | Details | Fix Needed |
|-------|----------|---------|------------|
| DB pool dependency | HIGH | `intake()` calls `cache_get()` which requires DB pool initialized | Ensure `create_pool()` called in FastAPI lifespan before any request |
| Cache hit returns cached output without re-verifying | MEDIUM | Cached `Phase1Output` returned as-is | Consider validating cached output schema on cache hit |
| Encrypted PDF rejection | LOW | `doc.is_encrypted` check exists; no password support | Not required for Phase 1 scope |
| No file type validation beyond header | LOW | Only checks `%PDF-` header | Acceptable for Phase 1 |

### Spec Gaps (Section 5)
| Spec Ref | Requirement | Current State | Gap |
|----------|-------------|---------------|-----|
| 5.1-5.2 | Accept resume or JD; prove file integrity via original_sha256 | Partially implemented | Missing DOCX/plain-text support |
| 5.2 | Check real type from first bytes (%PDF-, PK, valid text) | %PDF- check only | Missing PK/DOCX, plain text detection |
| 5.2 | Size and page limits | Implemented | OK |
| 5.2 | Encryption check | Implemented | OK |
| 5.2 | Archive bomb detection | NOT implemented | MISSING |
| 5.2 | PDF object tree scan for /JS, /JavaScript, etc. | NOT implemented | MISSING |
| 5.2 | Malware scan through scanner daemon | NOT implemented | MISSING |
| 5.3 | Version registry keyed by owner, job, track with CAS | NOT implemented | MISSING |
| 5.3 | Outcomes: READY, DUPLICATE, REJECTED, BLOCKED, FAILED, EXPIRED | Only READY/QUARANTINED | MISSING |
| 5.4 | Output: version_id, version_seq, original_sha256, file type, size, uploaded_at, track, outcome | Partial (sha256 only) | MISSING |

---

## Next Steps
1. Monitor `cache_get` DB dependency in production
2. Consider adding PDF structure validation beyond header magic bytes
3. Add metrics for cache hit rate
4. Implement DOCX/plain-text support per Section 5

---

## Relevant File Links
- `stages/s1_intake.py` — Stage 1 implementation
- `app/db.py` — `cache_get()` used in intake
- `app/pipeline.py` — calls `intake()`, handles `Stage1Error`
- `config/config.yaml` — intake config keys
- `tests/conftest.py` — `corrupt_pdf`, `oversized_pdf` fixtures
- `tests/test_pipeline.py` — cache hit, corrupt, oversized tests

---

## Checkpoint Status
**Status:** OPERATIONAL
**Last Verified:** 2026-11-27 — Stage 1 tests pass via pipeline integration tests
**Next Review:** When Stage 1 is aligned with spec Section 5
