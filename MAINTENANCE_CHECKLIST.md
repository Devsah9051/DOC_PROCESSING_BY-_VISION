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
| 26 | `app/scanner.py` | NEW: 4-stage scanner (magic-byte, zip-bomb, yara, CDR) replacing clamav daemon | DONE |
| 27 | `app/schemas.py` | Added ScanFinding, SanitizedArtifact models | DONE |
| 28 | `stages/s1_intake.py` | Integrated synchronous scan + CDR; added sanitized_artifact/scan_findings | DONE |
| 29 | `tests/test_scanner.py` | NEW: scanner tests | DONE |
| 30 | `app/scanner.py` | Conditional CDR: clean files skip CDR, targeted sanitization for medium findings | DONE |
| 31 | `app/pipeline.py` | Reopen doc from sanitized_bytes when cdr_applied=True; keep original when False | DONE |
| 32 | `stages/s3_govern.py` | govern_post accepts cdr_applied flag, adds CDR_APPLIED finding | DONE |
| 33 | `tests/test_scanner.py` | Added conditional CDR tests (clean text passthrough, text with external links) | DONE |
| 34 | `app/scanner.py` | Edge case fixes: encryption detection, structural parse check, raw_sha256, refined YARA severity (High/Medium) | DONE |
| 35 | `app/schemas.py` | Added raw_sha256, sanitized_artifact_uri to SanitizedArtifact | DONE |
| 36 | `tests/test_scanner.py` | Added raw_sha256 preserved, structural invalid, external_link medium tests | DONE |
| 37 | `ARCHITECTURE_DECISIONS.md` | NEW: ADR-001 through ADR-010 documenting all architectural decisions | DONE |
| 38 | `QUERY_LOG.md` | Added edge case hardening entry (ADR-011) | DONE |
| 39 | `stages/s4_structure.py` | Replaced thin extractor with full spec-compliant Stage 4: WordIndex O(1) lookup, position-aware section detection, date intervals with Present→as_of, labels (CONTRADICTION/CONFLICT/FACT/NOT_EVALUATED), rule families R1-R11/F1-F6/J1-J3, manipulation flags M1-M5, conservation ledger, sealed record_root/pii_ref, JD track support | DONE |
| 40 | `app/schemas.py` | Added DateInterval, ManipulationFlag, StructureResult models; rule/flag/label constants; Phase1Output structure fields | DONE |
| 41 | `app/pipeline.py` | Updated Stage 4 call to pass track/uploaded_at, consume StructureResult | DONE |
| 42 | `stages/s5_normalise.py` | Updated build_output() to accept structure_result and populate structure fields | DONE |
| 43 | `tests/test_s4_structure.py` | NEW: 8 tests for sections, fields, dates, rules, labels, manipulation flags, JD track, sealed output | DONE |
| 44 | `ARCHITECTURE_DECISIONS.md` | Added ADR-011 (Stage 4) and ADR-012 (Stage 5 integration); updated test count to 91 | DONE |

## Test Status
| Metric | Value |
|--------|-------|
| Total tests | 91 |
| Passed | 91 |
| Failed | 0 |
| Command | `DATABASE_URL=postgresql://postgres:password@localhost:5432/egca PYTHONPATH=. .venv/bin/pytest` |

## Environment Setup (COMPLETE)
| Task | Status | Notes |
|------|--------|-------|
| Python 3.11 venv at `.venv/` | DONE | `python3 -m venv .venv && .venv/bin/pip install uv` |
| Dependencies synced via `uv sync` | DONE | `pyproject.toml` deps installed |
| yara-python installed | DONE | `.venv/bin/pip install yara-python` |
| pikepdf installed | DONE | `.venv/bin/pip install pikepdf` |
| defusedxml installed | DONE | `.venv/bin/pip install defusedxml` |
| Docker PostgreSQL setup script | DONE | `scripts/setup_docker_postgres.sh` - starts postgres:16-alpine container, initializes schema, writes `.env` |
| `.env` created with DATABASE_URL + SEAL_KEY | DONE | Ed25519 key generated |
| FastAPI `/health` verified | DONE | Returns `{"status": "ok", "pipeline_version": "1.0.0"}` |

## Stub Work (README: Limitations)
| Stub | File | Status | Action Needed |
|------|------|--------|---------------|
| Stage 4.2 Latest-version check | `stages/s3_govern.py` | STUB | Wire to external service when spec fields exist |
| Stage 4.3 Job-open check | `stages/s3_govern.py` | STUB | Wire to external service when spec fields exist |
| Malware scanner | `app/scanner.py` | DONE | Synchronous yara+cdr pipeline in Stage 1; scan_enabled defaults to false |

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
| CDR output size monitoring | 200 DPI rendering may increase file size when CDR applied; only for Medium findings |

## Commands Reference
| Purpose | Command |
|---------|---------|
| Run tests | `DATABASE_URL=postgresql://postgres:password@localhost:5432/egca PYTHONPATH=. .venv/bin/pytest` |
| Install yara-python | `.venv/bin/pip install yara-python` |
| Install pikepdf | `.venv/bin/pip install pikepdf` |
| Install defusedxml | `.venv/bin/pip install defusedxml` |
| Run server | `DATABASE_URL=... SEAL_KEY=... PYTHONPATH=. .venv/bin/python -m uvicorn app.main:app` |
| Init DB | `DATABASE_URL=... .venv/bin/python scripts/init_db.py` |
| TTL cleanup | `DATABASE_URL=... .venv/bin/python scripts/init_db.py --cleanup` |
| Setup Docker PostgreSQL | `./scripts/setup_docker_postgres.sh` |
| Stop Docker PostgreSQL | `docker compose -f docker-compose.yml down -v` |

## Spec Compliance (EGCA Phase 1 Final Spec rev4)

A full spec-compliance review was completed against `/home/devsharma08/Downloads/EGCA_Phase_1_Final_Specification_rev4.docx`. All gaps are tracked in `SPEC_COMPLIANCE_CHECKLIST.md` and summarized per-stage in `checkpoints/*.md`.

**NOTE:** `SPEC_COMPLIANCE_CHECKLIST.md` Sections 4, 5, 8, 9 show outdated coverage — all Section 5 requirements are implemented per `checkpoints/stage1_intake.md`, Section 4 hash chain (record_root/stage5_root/file_state_hash) is wired per `app/hash.py` + `app/seal.py`, Section 8 (conservation ledger, labels, M1-M5, R/F/J rules, date intervals, record_root, pii_ref) is implemented per `checkpoints/stage4_structure.md`. The checklist file needs full syncing with current code.

### Stage 1: Intake (Section 5) — COMPLETE (~95%)

| Spec Ref | Requirement | Status |
|----------|-------------|--------|
| 5.1-5.2 | Accept resume or JD (PDF) | Complete |
| 5.1-5.2 | Accept DOCX/plain text | Complete (detection only; parsing in later stages) |
| 5.2 | File type from first bytes (%PDF-, PK, valid text) | Complete |
| 5.2 | Size limit | Complete |
| 5.2 | Page limit | Complete |
| 5.2 | Encryption check | Complete (pikepdf PasswordError) |
| 5.2 | Archive bomb detection | Complete (ZIP compression ratio + path traversal) |
| 5.2 | PDF object tree scan (/JS, /JavaScript, etc.) | Complete (yara-python rules) |
| 5.2 | Malware scan | Complete (synchronous yara+cdr pipeline) |
| 5.2 | Fingerprint: original_sha256 | Complete |
| 5.3 | Version registry with compare-and-swap | Complete (version_registry table) |
| 5.3 | Transactional outbox | Replaced by synchronous scan; outbox retained for other events |
| 5.3 | Outcomes: READY, DUPLICATE, REJECTED, BLOCKED, FAILED, EXPIRED | Complete |
| 5.4 | Output: version_id, version_seq, original_sha256, file type, size, uploaded_at, track, outcome, quarantine_pointer | Complete |

### Stage 1 Remaining Gaps (minor)
| Gap | Severity | Details |
|-----|----------|---------|
| Encrypted non-PDF files | LOW | pikepdf only detects PDF encryption; encrypted ZIP/DOCX not detected at intake |
| YARA external_link for PDFs | LOW | Compressed PDF streams hide URLs from string matching; external_link is Medium (stripped by CDR, not blocked) |

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
| P0 | Stage 4 structure (conservation ledger, labels, M2-M5) | 8 | `stages/s4_structure.py`, `app/schemas.py` | DONE |
| P0 | Stage 5 normalisation (provenance, relations, literal keys) | 9 | `stages/s5_normalise.py`, `app/schemas.py` | PARTIAL — provenance/relations via conservation ledger; relations pending |
| P1 | Stage 2 verdicts (CORROBORATED_FUZZY, ICON_GLYPH, TEXT_SOURCE) | 6.7 | `stages/s2_verify/verdict.py` |
| P1 | Stage 2 parse status (PARSED, PARSED_WITH_WARNINGS, PARTIAL, PARSE_FAILED) | 6.8 | `stages/s2_verify/__init__.py` |
| P1 | Run profile (all fields pinned) | 4.11 | `app/config.py`, `app/pipeline.py` |
| P1 | Stage 2 DOCX and plain text route | 6.12 | `stages/s2_verify/__init__.py` |
