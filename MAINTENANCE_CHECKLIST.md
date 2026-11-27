# Maintenance Checklist — EGCA Phase 1 DOC Processing

## Applied Patches (COMPLETE)
| # | File | Change | Status |
|---|------|--------|--------|
| 1 | `stages/s2_verify/render.py` | Fixed `add_redact_rect` → `add_redact_annot` (PyMuPDF API change) | DONE |
| 2 | `stages/s2_verify/render.py` | Fixed `_int_color` to handle list/tuple color values (not just int) | DONE |
| 3 | `stages/s2_verify/__init__.py` | Removed duplicate page-processing block (was doubling all flags) | DONE |
| 4 | `stages/s2_verify/__init__.py` | Fixed OCR loop: use `full_images[pno]` instead of `page_images[pno][0]` | DONE |
| 5 | `stages/s2_verify/__init__.py` | Changed render condition from `has_text_layer` (>=3 words) to `words` (any text) | DONE |
| 6 | `stages/s2_verify/verdict.py` | Fixed case-insensitive weight lookup | DONE |
| 7 | `stages/s2_verify/rules.py` | Fixed `int(word.get("flags", 0))` when `flags` is a list | DONE |
| 8 | `stages/s5_normalise.py` | Excluded `timings_ms` from `report_hash` (non-deterministic) | DONE |
| 9 | `app/pipeline.py` | Moved `record("stage5_normalise")` before `build_output` | DONE |
| 10 | `app/db.py` | Fixed variable shadowing: `database_url` parameter shadowed `database_url()` | DONE |
| 11 | `app/schemas.py` | Added `__getitem__` to `WordRecord` for dict-style access | DONE |
| 12 | `stages/s4_structure.py` | Separated `used_word_ids` sets: section vs field matching | DONE |
| 13 | `tests/test_s2_verify.py` | Fixed `np` import order in `test_contrast_low` | DONE |
| 14 | `app/hash.py` | NEW: Domain tags, canonical hashing, Section 4.1 | DONE |
| 15 | `app/log.py` | NEW: Append-only log with entry kinds, Section 4.3 | DONE |
| 16 | `app/seal.py` | Updated: sign stage5_root + file_state_hash, Section 4.2 | DONE |
| 17 | `app/schemas.py` | Updated: FileState, new statuses (CLEAN/REVIEW/QUARANTINE/FAILED) | DONE |
| 18 | `app/pipeline.py` | Updated: pre-gate/post-gate, hash chain flow, FAILED not QUARANTINE for bugs | DONE |
| 19 | `stages/s3_govern.py` | Updated: pre-gate/post-gate, suspicion rating, universal scan | DONE |
| 20 | `stages/s2_verify/verdict.py` | Updated: spec verdicts (CORROBORATED, etc.), thresholds (REVIEW/QUARANTINE) | DONE |
| 21 | `stages/s2_verify/rules.py` | Added: COVERED_BY_SHAPE rule, \u00b7 in ZERO_WIDTH chars | DONE |
| 22 | `tests/conftest.py` | Fixed: off_page fixture bbox, DB pool stub | DONE |
| 23 | `tests/test_pipeline.py` | Updated: status names, QUARANTINE→FAILED for errors | DONE |
| 24 | `tests/test_s2_verify.py` | Updated: status names, verdict thresholds | DONE |
| 25 | `tests/test_s3_govern.py` | Updated: govern_pre/govern_post dict return | DONE |

## Test Status
| Metric | Value |
|--------|-------|
| Total tests | 41 |
| Passed | 41 |
| Failed | 0 |
| Command | `DATABASE_URL=postgresql://postgres:password@localhost:5432/egca PYTHONPATH=. .venv/bin/pytest` |

## Environment Setup (COMPLETE)
| Task | Status | Notes |
|------|--------|-------|
| Python 3.11 venv at `.venv/` | DONE | `python3 -m venv .venv && .venv/bin/pip install uv` |
| Dependencies synced via `uv sync` | DONE | `pyproject.toml` deps installed |
| Docker PostgreSQL setup script | DONE | `scripts/setup_docker_postgres.sh` - starts postgres:16-alpine container, initializes schema, writes `.env` |
| `.env` created with DATABASE_URL + SEAL_KEY | DONE | Ed25519 key generated |
| FastAPI `/health` verified | DONE | Returns `{"status": "ok", "pipeline_version": "1.0.0"}` |

## Stub Work (README: Limitations)
| Stub | File | Status | Action Needed |
|------|------|--------|---------------|
| Stage 4.2 Latest-version check | `stages/s3_govern.py` | STUB | Wire to external service when spec fields exist |
| Stage 4.3 Job-open check | `stages/s3_govern.py` | STUB | Wire to external service when spec fields exist |

## Database Maintenance
| Task | Command | Frequency |
|------|---------|-----------|
| TTL cleanup (personal data retention) | `python scripts/init_db.py --cleanup` | Periodic (default 30 days) |
| Database backup | `pg_dump egca > backup.sql` | Before schema changes |
| Connection pool check | Monitor `psycopg_pool` usage | Ongoing |

## Ongoing Maintenance
| Task | Details |
|------|---------|
| Threshold tuning | `suspicious_score`, `contrast_min`, `min_ink`, `ghost_diff_threshold` tuned on synthetic fixtures only |
| PaddleOCR model download | First OCR run downloads models (may be slow) |
| Real-world validation | Thresholds need tuning on real resume/JD PDFs |
| Personal-data retention | Resumes stored in audit log; TTL cleanup recommended |

## Commands Reference
| Purpose | Command |
|---------|---------|
| Run tests | `DATABASE_URL=postgresql://postgres:password@localhost:5432/egca PYTHONPATH=. .venv/bin/pytest` |
| Run server | `DATABASE_URL=... SEAL_KEY=... PYTHONPATH=. .venv/bin/python -m uvicorn app.main:app` |
| Init DB | `DATABASE_URL=... .venv/bin/python scripts/init_db.py` |
| TTL cleanup | `DATABASE_URL=... .venv/bin/python scripts/init_db.py --cleanup` |
| Setup Docker PostgreSQL | `./scripts/setup_docker_postgres.sh` |
| Stop Docker PostgreSQL | `docker compose -f docker-compose.yml down -v` |

## Spec Compliance (EGCA Phase 1 Final Spec rev4)

A full spec-compliance review was completed against `/home/devsharma08/Downloads/EGCA_Phase_1_Final_Specification_rev4.docx`. All gaps are tracked in `SPEC_COMPLIANCE_CHECKLIST.md` and summarized per-stage in `checkpoints/*.md`.

### Highest-Priority Remediation Items

| Priority | Item | Spec Section | Files to Change |
|----------|------|--------------|-----------------|
| P0 | Programming errors must be FAILED, never QUARANTINE | 6.13, 11 | `app/pipeline.py`, `stages/s2_verify/__init__.py` |
| P0 | Hash chain with domain tags | 4.1, 4.2 | `app/seal.py`, `app/schemas.py`, `app/pipeline.py` |
| P0 | Append-only log with entry kinds | 4.3 | `app/db.py`, new `app/log.py` |
| P0 | Independent verifier (3 levels) | 4.5 | new `app/verifier.py` |
| P0 | Stage 3 pre-gate/post-gate split | 7.2 | `stages/s3_govern.py`, `app/pipeline.py` |
| P0 | Universal injection scan (separate from Stage 2) | 7.3 | `stages/s3_govern.py` |
| P0 | Suspicion rating with weights/thresholds | 7.4 | `stages/s3_govern.py`, `app/config.py` |
| P0 | Stage 2 frame splitting | 6.2 | `stages/s2_verify/__init__.py` |
| P0 | Stage 4 structure (conservation ledger, labels, M2-M5) | 8 | `stages/s4_structure.py`, `app/schemas.py` |
| P0 | Stage 5 normalisation (provenance, relations, literal keys) | 9 | `stages/s5_normalise.py`, `app/schemas.py` |
| P1 | Stage 1 DOCX/plain-text/outcomes/version registry | 5 | `stages/s1_intake.py`, `app/schemas.py` |
| P1 | Stage 2 verdicts (CORROBORATED_FUZZY, ICON_GLYPH, TEXT_SOURCE) | 6.7 | `stages/s2_verify/verdict.py` |
| P1 | Stage 2 parse status (PARSED, PARSED_WITH_WARNINGS, PARTIAL, PARSE_FAILED) | 6.8 | `stages/s2_verify/__init__.py` |
| P1 | Run profile (all fields pinned) | 4.11 | `app/config.py`, `app/pipeline.py` |