# TODO — Completed Functional Features (EGCA Phase 1)

This file lists every functional feature that has been implemented and verified in the codebase, grouped by the pipeline stage from the EGCA Phase 1 Final Specification rev4. Features marked **DONE** are implemented and covered by tests. Features marked **STUB** are present as interfaces/stubs but not wired to external services or fully implemented.

Source document: `/home/devsharma08/Downloads/EGCA_Phase_1_Final_Specification_rev4.docx`

## Per-stage documentation

Each stage has a dedicated folder with its own README:

| Stage | Folder | README |
|---|---|---|
| 1 Upload / Intake | `stage_1_upload/` | `stage_1_upload/README.md` |
| 2 Verify | `stage_2_verify/` | `stage_2_verify/README.md` |
| 3 Govern | `stage_3_govern/` | `stage_3_govern/README.md` |
| 4 Structure | `stage_4_structure/` | `stage_4_structure/README.md` |
| 5 Normalise | `stage_5_normalise/` | `stage_5_normalise/README.md` |


---

## Stage 1 — Upload and Intake (spec Section 5)

| Feature | Status | Notes |
|---|---|---|
| File size cap enforcement (max_bytes) | DONE | `stages/s1_intake.py` |
| Safe filename validation | DONE | `stages/s1_intake.py` |
| PDF header (%PDF-) validation | DONE | `stages/s1_intake.py` |
| SHA-256 fingerprint (original_sha256) | DONE | carried as `prev_hash` through pipeline |
| Encrypted PDF rejection | DONE | `stages/s1_intake.py` |
| Page count limit (max_pages) | DONE | `stages/s1_intake.py` |
| Max pixels per page limit (max_pixels) | DONE | `stages/s1_intake.py` |
| Result cache lookup (sha256 + versions) | DONE | `app/db.py` `cache_get`, stubbed in tests |
| DOCX conversion + structure scan route | STUB | spec 6.12 not implemented |
| Plain-text TEXT route | STUB | spec 6.12 not implemented |
| Malware scan via scanner daemon | STUB | optional in v1 |
| Version registry with compare-and-swap | STUB | not implemented |
| Transactional outbox for outcome announcement | STUB | not implemented |
| Write-once quarantine storage | STUB | not implemented |

---

## Stage 2 — Verify (Parse and Visual Verification) (spec Section 6)

| Feature | Status | Notes |
|---|---|---|
| Text layer extraction (spans: colour, size, opacity, font, render mode) | DONE | `stages/s2_verify/__init__.py` |
| Cheap rule: TINY_FONT | DONE | `stages/s2_verify/rules.py` |
| Cheap rule: INVISIBLE_OPACITY | DONE | `stages/s2_verify/rules.py` |
| Cheap rule: INVISIBLE_RENDER_MODE | DONE | `stages/s2_verify/rules.py` |
| Cheap rule: OFF_PAGE | DONE | `stages/s2_verify/rules.py` |
| Cheap rule: ZERO_WIDTH_CHAR | DONE | `stages/s2_verify/rules.py` |
| Cheap rule: BIDI_CHAR | DONE | `stages/s2_verify/rules.py` |
| Cheap rule: TAG_CHAR | DONE | `stages/s2_verify/rules.py` |
| Cheap rule: MIXED_SCRIPT | DONE | `stages/s2_verify/rules.py` |
| Cheap rule: PRIVATE_USE | DONE | `stages/s2_verify/rules.py` |
| Cheap rule: GARBLED | DONE | `stages/s2_verify/rules.py` |
| Font rule: FONT_ANOMALY (Type3/custom) | DONE | `stages/s2_verify/rules.py` |
| Font rule: GARBLED with anomaly font | DONE | `stages/s2_verify/rules.py` |
| Ghost diff (text erased vs original render) | DONE | `stages/s2_verify/render.py` |
| Luminance contrast ratio check (WCAG) | DONE | `stages/s2_verify/render.py` |
| OCR region via PaddleOCR (CPU singleton) | DONE | `stages/s2_verify/ocr.py` |
| Injection scan: strong patterns | DONE | `stages/s2_verify/rules.py` |
| Injection scan: weak patterns | DONE | `stages/s2_verify/rules.py` |
| Injection scan on metadata | DONE | `stages/s2_verify/__init__.py` |
| Injection scan on links | DONE | `stages/s2_verify/__init__.py` |
| Injection scan on annotations | DONE | `stages/s2_verify/__init__.py` |
| Verdict: QUARANTINED (strong injection) | DONE | `stages/s2_verify/verdict.py` |
| Verdict: SUSPICIOUS (weighted score >= threshold) | DONE | `stages/s2_verify/verdict.py` |
| Verdict: CLEAN | DONE | `stages/s2_verify/verdict.py` |
| Clean text building with reading order | DONE | `stages/s2_verify/verdict.py` |
| Matched / OCR_ONLY classification | DONE | `stages/s2_verify/verdict.py` |
| Audit sample selection keyed by SHA-256 | DONE | `stages/s2_verify/__init__.py` |
| Frame cutting from rendered image | STUB | per-word regions used, not frames |
| Full-page OCR for scans | STUB | partial (region OCR only) |
| DOCX conversion + structure scan | STUB | spec 6.12 |
| Plain-text TEXT route | STUB | spec 6.12 |
| Forensic bundle write (forensic_ref) | STUB | not implemented |
| Page rotation / deskew | STUB | spec 6.11 |
| Repeated headers / footers (PAGE_FURNITURE) | STUB | spec 6.11 |
| Watermark handling | STUB | spec 6.11 |
| Hyphen / letter-spaced repair | STUB | spec 6.11 |

---

## Stage 3 — Govern (Ingestion and Governance) (spec Section 7)

| Feature | Status | Notes |
|---|---|---|
| Audit log insert per upload_id | DONE | `stages/s3_govern.py` `govern()` |
| QUARANTINED stop (stages 4-5 skipped) | DONE | `stages/s3_govern.py` |
| Stub: latest_version_ok() | STUB | returns True, not wired |
| Stub: job_open_ok() | STUB | returns True, not wired |
| Idempotency key + check | STUB | not implemented |
| Epoch fencing / version_seq | STUB | not implemented |
| State watcher (JOB_CLOSED, APPLICATION_WITHDRAWN) | STUB | not implemented |
| Result cache lookup and reuse | STUB | partially in Stage 1 only |
| Near-duplicate check | STUB | not implemented |
| Transactional outbox for gate decisions | STUB | not implemented |
| Suspicion rating with severity weights | STUB | not implemented as separate post-gate |
| Universal scan as separate post-gate step | STUB | injection scan runs in Stage 2 |
| file_state_hash computation and sealing | STUB | not implemented |
| Append-only log with entry kinds | STUB | not implemented |

---

## Stage 4 — Structure (spec Section 8)

| Feature | Status | Notes |
|---|---|---|
| Section detection via alias dictionary | DONE | `stages/s4_structure.py` |
| Field extraction: email | DONE | `stages/s4_structure.py` |
| Field extraction: phone | DONE | `stages/s4_structure.py` |
| Field extraction: date | DONE | `stages/s4_structure.py` |
| Date consistency: future dates | DONE | `stages/s4_structure.py` |
| Date consistency: end-before-start | DONE | `stages/s4_structure.py` |
| Word span/bbox association for fields and sections | DONE | `stages/s4_structure.py` |
| Full section detection signals (layout, position, content shape) | STUB | alias matching only |
| Conservation ledger | STUB | not implemented |
| Labels (CONTRADICTION, CONFLICT, FACT, NOT_EVALUATED) | STUB | not implemented |
| Rule families R1-R11, F1-F6, J1-J3 | STUB | not implemented |
| Manipulation flags M2-M5 | STUB | M1 exists in Stage 2 verdict only |
| record_root computation and sealing | STUB | not implemented |
| pii_ref for identity separation | STUB | not implemented |
| Job-description requirement extraction | STUB | not implemented |
| DRS (requirement set seal) | STUB | not implemented |

---

## Stage 5 — Normalise (spec Section 9)

| Feature | Status | Notes |
|---|---|---|
| Taxonomy loading from YAML | DONE | `stages/s5_normalise.py`, `config/taxonomy.yaml` |
| Skill normalisation: exact match | DONE | `stages/s5_normalise.py` |
| Skill normalisation: alias match | DONE | `stages/s5_normalise.py` |
| Skill normalisation: fuzzy match (rapidfuzz >= 85) | DONE | `stages/s5_normalise.py` |
| Deduplication (each canonical skill once) | DONE | `stages/s5_normalise.py` |
| word_ids aggregation per skill | DONE | `stages/s5_normalise.py` |
| Related skills from taxonomy carried through | DONE | `stages/s5_normalise.py` |
| Output building with canonical hash | DONE | `stages/s5_normalise.py` `build_output` |
| Ed25519 seal on output | DONE | `stages/s5_normalise.py` + `app/seal.py` |
| Deterministic output (same input + versions = same hash) | DONE | verified by tests |
| Result cache write | DONE | `stages/s5_normalise.py` `write_cache` |
| Value normaliser (durations, degrees, grades) | STUB | not implemented |
| Negative-pair file (Java/JavaScript, C/C#) | STUB | not implemented |
| Provenance tag PROPOSED_AGREED / INFERRED | STUB | not implemented |
| Status PRESENT / MISSING / NOT_ACCEPTED tracking | STUB | not implemented |
| Aggregator with counts | STUB | not implemented |
| Skill relations table (family, ecosystem, relation classes) | STUB | not implemented |
| record_root intake verification | STUB | not implemented |
| stage5_root computation | STUB | report_hash used as output hash |
| Taxonomy maintenance via decision service | STUB | not implemented |
| Literal key for UNMAPPED terms | STUB | not implemented |
| Job-description requirement normalisation | STUB | not implemented |

---

## Cross-cutting

| Feature | Status | Notes |
|---|---|---|
| Ed25519 signing (sign/verify) | DONE | `app/seal.py` |
| FastAPI /phase1 endpoint | DONE | `app/main.py` |
| Config loading from YAML | DONE | `app/config.py`, `config/config.yaml` |
| DB layer: cache_get / cache_insert / audit_insert | DONE | `app/db.py`, stubbed in tests |
| DB pool creation | DONE | `app/db.py` `create_pool` |
| Pipeline orchestration (run_phase1) | DONE | `app/pipeline.py` |
| Pydantic schemas (Phase1Output, Verdict, WordRecord, etc.) | DONE | `app/schemas.py` |

---

## Test coverage

28 passing pytest tests across:
- `tests/test_pipeline.py` — end-to-end pipeline (clean, corrupt, oversized, injection, tiny font, off-page, zero-width, white-on-white, covered text, two-column, cache hit, versions/timings)
- `tests/test_s2_verify.py` — Stage 2 rules, render, ghost diff, contrast, verdict, classification
- `tests/test_s3_govern.py` — Stage 3 govern and stubs
- `tests/test_s4_structure.py` — Stage 4 section and field extraction
- `tests/test_s5_normalise.py` — Stage 5 normalisation and seal
- `tests/test_seal.py` — Ed25519 sign/verify roundtrip

DB-dependent features are stubbed via `tests/conftest.py` so tests run without live PostgreSQL.
