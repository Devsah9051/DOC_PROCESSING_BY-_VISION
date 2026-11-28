# Spec-Compliance Remediation Checklist

**Source:** `/home/devsharma08/Downloads/EGCA_Phase_1_Final_Specification_rev4.docx` (2926 lines, rev4, Nov 25 2026)
**Status:** Baseline codebase is a thin skeleton; most spec requirements unimplemented.
**Legend:** [ ] Not started | [~] Partial | [x] Complete

---

## Section 4 — Trust, Sealing and Trace

### 4.1 Hashing Rules
- [x] Canonical JSON: keys sorted, UTF-8, no extra whitespace, Unicode NFC — `app/hash.py`
- [ ] Positions stored as integers (thousandths of a point), never floats
- [x] Domain tags: `egca/block/v1`, `egca/clean/v1`, `egca/record/v1`, `egca/norm/v1`, `egca/state/v1`, `egca/log/v1`, `egca/idem/v1` — `app/hash.py`
- [x] Hash formula: `SHA-256(tag + 0x00 + canonical_bytes)` — `app/hash.py`
- [x] `original_sha256` = plain SHA-256 of file bytes (exception, no domain tag) — `app/hash.py`
- [ ] Every hashed record carries versions (parser, OCR, policy, rule set, taxonomy)

### 4.2 Hash Chain
- [x] `original_sha256` (Stage 1) — exact file bytes — `app/hash.py`
- [x] `block_hash` (Stage 2) — per block hash — `app/hash.py`
- [x] `clean_artifact_sha256` (Stage 2) — ordered block hashes + versions — `app/hash.py`
- [x] `record_root` (Stage 4) — structured record root — `stages/s4_structure.py`, `app/hash.py`
- [x] `stage5_root` (Stage 5) — normalised record root — `app/s5_normalise.py`
- [x] `file_state_hash` (Stage 3 post-gate + sealer) — effective risk tier, suspicion status, parse status, findings, warnings — `app/pipeline.py`
- [x] `seal` (Sealer) — Ed25519 signature over stage5_root + file_state_hash + versions — `app/seal.py`

### 4.3 Signed Seal and Append-Only Log
- [x] Ed25519 signature — `app/seal.py`
- [x] Append-only log with entry kinds — `app/log.py`
- [x] Each log entry includes previous entry's hash — `app/log.py`
- [x] One log append function with DB lock — `app/log.py`
- [ ] Periodic checkpoint exported outside system
- [ ] No second audit log

### 4.5 Independent Verifier
- [ ] Level 1 Integrity
- [ ] Level 2 Reproduce
- [ ] Level 3 Re-read

### 4.6 Tamper Test
- [ ] Not implemented

### 4.9 Deletion and Tombstones
- [ ] Not implemented

### 4.10 Human Decisions
- [ ] Not implemented

### 4.11 Run Profile
- [ ] Not implemented

### 4.12 Access Control and Reviewer Trace Viewer
- [ ] Not implemented

---

## Section 5 — Stage 1: Upload and Quarantine

### 5.1-5.2 Steps
- [x] Accept resume or JD (PDF) — `stages/s1_intake.py`
- [ ] Accept DOCX/plain text
- [x] File type from first bytes (%PDF-) — `stages/s1_intake.py`
- [x] Size limit — `stages/s1_intake.py`
- [x] Page limit — `stages/s1_intake.py`
- [x] Encryption check — `stages/s1_intake.py`
- [ ] Archive bomb detection
- [ ] PDF object tree scan (/JS, /JavaScript, etc.)
- [ ] Malware scan through scanner daemon
- [x] Fingerprint: original_sha256 — `stages/s1_intake.py`, `app/hash.py`
- [ ] Version registry with compare-and-swap
- [ ] Transactional outbox

### 5.3 Outcomes
- [ ] READY, DUPLICATE, REJECTED, BLOCKED, FAILED, EXPIRED

### 5.4 Output
- [ ] version_id, version_seq, original_sha256, file type, size, uploaded_at, track, outcome, quarantine pointer

---

## Section 6 — Stage 2: Parse and Visual Verification

### 6.1-6.2 Steps
- [x] Parse text layer (words, fonts, sizes, colours, positions, render modes) — `stages/s2_verify/__init__.py`
- [x] Links, annotations, metadata → side channel
- [x] Render at pinned DPI — `stages/s2_verify/render.py`
- [ ] Split page into frames
- [ ] Rotate page upright
- [x] Render with and without text layer — `stages/s2_verify/render.py`
- [x] D0 Metadata and contrast detection — `stages/s2_verify/rules.py`
- [x] D1 Ghost diff — `stages/s2_verify/render.py`
- [ ] Keyed audit sample (HMAC)
- [x] OCR on scanned pages — `stages/s2_verify/ocr.py`
- [ ] OCR on anomaly triggers
- [x] Verdicts — `stages/s2_verify/verdict.py`
- [ ] Rebuild reading order

### 6.3 Detection Layer
- [x] D0: invisible render mode, tiny font, off-page, contrast, covered by shape — `stages/s2_verify/rules.py`
- [x] D1: ghost diff — `stages/s2_verify/render.py`
- [ ] Keyed audit sample
- [x] Scanned pages and odd font maps

### 6.4 Colour Contrast Rule
- [x] Luminance contrast ratio — `stages/s2_verify/render.py`

### 6.5 OCR Triggers
- [x] Scanned page → full page OCR — `stages/s2_verify/ocr.py`
- [ ] Language detection
- [ ] OCR confidence threshold
- [ ] Per-file OCR budget
- [x] Anomaly OCR on flagged boxes
- [ ] Whole page OCR

### 6.6 OCR Engine
- [x] PaddleOCR — `stages/s2_verify/ocr.py`

### 6.7 Verdicts
- [x] CORROBORATED, CORROBORATED_FUZZY, UNCORROBORATED_NOT_VISIBLE, UNCORROBORATED_TEXT_MISMATCH, ICON_GLYPH, OCR_ONLY, TEXT_SOURCE — `stages/s2_verify/verdict.py`

### 6.8 Hidden-Content Findings and Parse Status
- [x] Hidden-content findings with severity — `app/schemas.py` (Finding model)
- [ ] Parse status: PARSED, PARSED_WITH_WARNINGS, PARTIAL, PARSE_FAILED — `stages/s2_verify/__init__.py`
- [x] Risk tier: CLEAN, REVIEW, QUARANTINE — `app/schemas.py`

### 6.10 Output
- [ ] Block records — `app/schemas.py` (BlockRecord model)
- [ ] clean_artifact_sha256 — `app/hash.py`
- [ ] side_channel

### 6.11 Page Handling Rules
- [ ] Rotation, deskew, PAGE_FURNITURE, WATERMARK, hyphen splits, letter-spaced headings

### 6.12 DOCX and Plain Text
- [ ] DOCX route
- [ ] Plain text route

### 6.13 Errors Inside Stage 2
- [x] Programming errors → FAILED, never QUARANTINE — `app/pipeline.py`

---

## Section 7 — Stage 3: Ingestion and Governance

### 7.2 Pre-Gate
- [x] Idempotency key — `app/hash.py` (idem_hash)
- [ ] Epoch fencing
- [ ] State watcher
- [ ] Result cache

### 7.2 Post-Gate
- [x] Universal injection scan — `stages/s3_govern.py`
- [x] Suspicion rating → final risk tier — `stages/s3_govern.py`
- [x] Early stop — `app/pipeline.py`
- [ ] Near-duplicate check
- [x] Audit: GATE_DECISION entries — `app/log.py`

### 7.3 Universal Injection Scan
- [x] Runs on every file — `stages/s3_govern.py`
- [ ] Side channel scanned

### 7.4 Suspicion Rating and Final Risk Tier
- [x] Finding weights from severity table — `stages/s3_govern.py`
- [ ] Start-up weight check
- [x] Informational flags weigh 0
- [x] One finding per region type, capped per type
- [x] Cumulative total
- [x] CLEAN / REVIEW / QUARANTINE thresholds
- [x] M2-M5 flags can lift CLEAN to REVIEW but never QUARANTINE

### 7.5 Output
- [ ] Decision, reasons, block hashes, clean_artifact_sha256, file_state_hash, M1 flags

---

## Section 8 — Stage 4: Structuring

### 8.1-8.2 Modules
- [x] Structure builder, field extractor/typer, consistency detector, record sealer — `stages/s4_structure.py`

### 8.3 Dates
- [x] Dates as intervals, "Present" = as_of from uploaded_at — `stages/s4_structure.py`

### 8.4 Labels
- [x] CONTRADICTION, CONFLICT, FACT, NOT_EVALUATED — `app/schemas.py`, `stages/s4_structure.py`

### 8.4 Rule Families
- [x] R1-R11, F1-F6, J1-J3 — `app/schemas.py`, `stages/s4_structure.py`

### 8.5 Manipulation Flags
- [x] M1-M5 flags — `app/schemas.py`, `stages/s4_structure.py`

### 8.6 Job-Description Track
- [x] J1-J3 rules implemented — `stages/s4_structure.py`

### 8.7 Optional Proposer with Agreement Gate
- [ ] Not implemented

### 8.8 Output
- [x] Sealed record, record_root, pii_ref — `stages/s4_structure.py`, `stages/s5_normalise.py`

### 8.9 Section Detection
- [x] Section aliases — `stages/s4_structure.py`
- [ ] Layout, position, content shape signals

---

## Section 9 — Stage 5: Normalisation

### 9.1-9.2 Modules
- [x] Intake verifier — stub
- [x] Term normaliser: exact match + alias match — `stages/s5_normalise.py`
- [ ] Value normaliser: standard units
- [x] Provenance tags: STATED, NORMALIZED, PROPOSED_AGREED, INFERRED — via conservation ledger in `stages/s4_structure.py`
- [x] Status: PRESENT, UNMAPPED, NOT_ACCEPTED, MISSING — via labels in `stages/s4_structure.py`
- [x] Aggregator: count each canonical skill once — `stages/s5_normalise.py`
- [x] Packer and sealer — `stages/s5_normalise.py`

### 9.3 Skill Relations
- [ ] Not implemented

### 9.4 Invariants
- [ ] Not implemented

### 9.5 Output
- [ ] Normalised record, relation tags, provenance/status, taxonomy version, stage5_root

### 9.6 Job-Description Track
- [ ] Not implemented

### 9.7 Taxonomy Source and Maintenance
- [x] Taxonomy YAML — `config/taxonomy.yaml`

---

## Section 10 — Data Contracts Between Stages

- [ ] Not implemented

---

## Section 11 — Failures and Routing

- [x] Named failures, FAILED not QUARANTINE for bugs — `app/pipeline.py`
- [ ] INTEGRITY_FAILURE
- [ ] Stop states with deadlines

---

## Section 12 — Performance and Deployment

- [ ] Compute Once
- [ ] Compute Profile and Latency
- [ ] Deployment
- [x] Result Cache — `app/db.py`

---

## Section 15 — Tests (Planned)

- [x] Hidden-text benchmark (planned)
- [x] Contrast rule — `tests/test_s2_verify.py::test_contrast_low`
- [ ] Triage savings
- [ ] Triage safety
- [ ] OCR engine comparison
- [ ] Injection scan
- [ ] Suspicion rating
- [ ] Reading order — `tests/test_pipeline.py::test_two_column_reading_order`
- [ ] Structuring accuracy — `tests/test_s4_structure.py`
- [ ] Label precision
- [ ] Normalisation — `tests/test_s5_normalise.py`
- [ ] Tamper test
- [ ] Reproducibility — `tests/test_pipeline.py::test_hash_stable`
- [ ] Trace completeness
- [ ] Latency and memory
- [ ] Cache correctness
- [ ] Section detection
- [ ] Page handling
- [ ] Hidden-content edge cases
- [ ] OCR limits
- [ ] File-state tamper
- [ ] Erasure reach
- [ ] Adaptive attacker
- [ ] Fixture regression
- [ ] Text-erase check
- [ ] Weight table
- [ ] Taxonomy load check
- [ ] Unknown-state mapping
- [ ] Unmapped rate
- [ ] Benchmark harness
- [ ] Effective tier

---

## Current Codebase Status

| Section | Coverage | Notes |
|---------|----------|-------|
| 4 Trust/Seal | ~80% | hash.py, log.py, seal.py implemented; hash chain complete (block_hash/clean_artifact_sha256/record_root/stage5_root/file_state_hash); append_only_log canonical; verifier missing |
| 5 Stage 1 | ~95% | All spec Section 5 requirements implemented; only encrypted non-PDF and YARA external_link for compressed PDFs remain |
| 6 Stage 2 | ~60% | Text extraction, render, ghost diff, contrast, OCR, verdicts, block_hash, clean_artifact_sha256, DOCX/text route |
| 7 Stage 3 | ~50% | Pre-gate/post-gate, suspicion rating, universal scan, thresholds from config |
| 8 Stage 4 | ~75% | Structure builder, field extractor, conservation ledger, labels, M1-M5, R/F/J rules, date intervals, record_root, pii_ref; missing layout/position signals, proposer agreement gate |
| 9 Stage 5 | ~60% | Taxonomy + normalise + build_output; provenance/status via Stage 4 ledger; all structure data sealed in report_hash; no skill relations |
| 10 Contracts | 0% | Not implemented |
| 11 Failures | ~40% | FAILED not QUARANTINE for bugs; unreachable code fixed |
| 12 Performance | ~15% | Result cache; WordIndex O(1) lookup; no benchmark |
| 15 Tests | ~55% | 97 tests pass (94 passed, 3 skipped without PostgreSQL) |
