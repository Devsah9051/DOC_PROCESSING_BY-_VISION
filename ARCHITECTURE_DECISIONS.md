# Architecture Decision Record — EGCA Phase 1 DOC Processing

This document lists all architectural decisions for the DOC_PROCESSING_BY_VISION project, including the latest conditional CDR change.

---

## Decision ADR-001: Stage 1 Intake — File Type Support

**Status:** Implemented  
**Scope:** `stages/s1_intake.py`, `app/db.py`, `scripts/init_db.py`

Accept PDF, DOCX, and plain text uploads. File type detected from magic bytes (`%PDF-`, `PK\x03\x04`, valid UTF-8). Rejects unknown binary types.

**Outcome model:** READY, DUPLICATE, REJECTED, BLOCKED, FAILED, EXPIRED.

**Version registry:** Compare-and-swap registration keyed by `(sha256, track)` in `version_registry` table.

---

## Decision ADR-002: Stage 1 Intake — Malware Scanner Architecture (REVISED)

**Status:** Implemented  
**Scope:** `app/scanner.py`, `app/schemas.py`, `app/config.py`, `config/config.yaml`, `stages/s1_intake.py`, `app/pipeline.py`, `stages/s3_govern.py`

### Original (replaced)
Async scanner daemon (`scripts/run_scanner.py`) + clamav + transactional outbox pattern. Outbox entries (`file_scan_requested`) written alongside business data, processed by a polling daemon that writes results to `scan_results` table.

### Current (replacement)
**Synchronous 4-stage scanner pipeline in Stage 1 with conditional CDR:**

| Stage | Component | Action |
|-------|-----------|--------|
| 1 | Magic-Byte Check | Rejects spoofed extensions / non-PDF & non-DOCX binaries |
| 2 | Encryption Check | Rejects password-protected/corrupt PDFs (422) before YARA can't see inside |
| 3 | Zip-Bomb Guard | Rejects recursive/oversized DOCX archives & path traversal |
| 4 | yara-python scan | Detects embedded JS, auto-actions, VBA macros, DDE, external links |
| 5 | Structural Parse Check | pikepdf/pymupdf for PDF, defusedxml for DOCX — runs even on no-findings branch |
| 6 | CDR Reconstruction (conditional) | Applied ONLY when YARA finds Medium findings; High → BLOCKED |

**Removed:** `scripts/run_scanner.py`, clamav dependency, async outbox scan flow for malware.

**SanitizedArtifact output:** `sha256`, `raw_sha256` (immutable original hash), `file_type`, `original_size`, `sanitized_size`, `sanitized_bytes`, `scan_engine`, `infected`, `threat_name`, `findings`, `cdr_applied`, `cdr_method`, `sanitized_artifact_uri`, `scanned_at`.

---

## Decision ADR-003: Stage 1 Intake — Conditional CDR with Edge Case Hardening

**Status:** Implemented  
**Scope:** `app/scanner.py`, `app/pipeline.py`, `stages/s3_govern.py`

### Four edge cases addressed:

**Edge Case 1 — Zero-Day / Malformed Parser Blind Spot:**
Even on the "No findings" branch (YARA found nothing), a structural parse check runs:
- PDF: `pikepdf.open()` with page iteration, fallback to `pymupdf.open()` if pikepdf fails
- DOCX: `defusedxml.parse()` of `word/document.xml`
- If parsing fails → BLOCKED → QUARANTINE (never reaches Stage 2 with a corrupt file)

**Edge Case 2 — Encrypted / Password-Protected PDFs:**
Detected immediately after magic-byte check (before YARA). `pikepdf.open()` raises `PasswordError` → reject with clear reason. Never reaches YARA (which can't see inside encrypted streams).

**Edge Case 3 — Immutable Raw Bytes Preserved:**
`raw_sha256` field stores the SHA-256 of the original upload, immutable even after CDR. `sanitized_artifact_uri` field records where the derived sanitized artifact is stored. Both hashes recorded in PostgreSQL audit table for forensic reproducibility.

**Edge Case 4 — Refined YARA Severity Classification:**
- **High (always quarantine, never strip):** `/JavaScript`, `/JS`, `/OpenAction`, `/AA`, `/Launch`, `/RichMedia`, `/EmbeddedFile`, `/XFA`, `vbaProject.bin`, `DDEAUTO`, `PasswordError`
- **Medium (safe to strip with targeted sanitization):** `/Metadata` (XMP), `/AcroForm` (non-XFA), `/Annotations`, external links (`http://`, `https://`, `file://`), DOCX custom properties (`docProps/custom.xml`)
- ZIP bomb detection moved from YARA (false positive on `PK` signature) to dedicated `zip_bomb_guard()`

---

## Decision ADR-004: Stage 3 Govern — Pre-gate / Post-gate Split

**Status:** Implemented  
**Scope:** `stages/s3_govern.py`, `app/pipeline.py`

**`govern_pre()`:** Runs before parsing. Checks idempotency cache, Stage 1 scan findings (Medium findings → REVIEW tier), epoch fencing stubs. Returns `{"proceed": bool, "reason": str}`.

**`govern_post()`:** Runs after Stage 2. Universal injection scan, suspicion rating with weights/thresholds, file state construction. Accepts `scan_findings` and `cdr_applied` from Stage 1. Returns `{"proceed": bool, "reason": str, "file_state": FileState}`.

**Suspicion rating:** Weighted sum of findings by severity (High/Medium/Low). Thresholds: REVIEW vs QUARANTINE.

---

## Decision ADR-005: Stage 2 Verify — No Re-scanning for Malware

**Status:** Implemented  
**Scope:** `stages/s2_verify/__init__.py`

Stage 2 trusts Stage 1's scan results. Clean files (`cdr_applied=False`) go through fast-path text extraction. Files where CDR was applied may require OCR path. No redundant malware scanning in Stage 2.

---

## Decision ADR-006: Database Schema — Tables

**Status:** Implemented  
**Scope:** `scripts/init_db.py`, `app/db.py`

| Table | Purpose |
|-------|---------|
| `version_registry` | CAS version registration keyed by `(sha256, track)` |
| `outbox` | Transactional outbox for reliable event publishing (retained for non-scan events) |
| `scan_results` | Malware scan results keyed by `sha256`; extended data in `payload` JSONB (original_size, sanitized_size, findings, cdr_applied, cdr_method) |
| `governance_audit_log` | Audit trail for gate decisions |

---

## Decision ADR-007: Config — Intake + Scanner Settings

**Status:** Implemented  
**Scope:** `app/config.py`, `config/config.yaml`

| Key | Default | Purpose |
|-----|---------|---------|
| `max_bytes` | 10,000,000 | Max file size |
| `max_pages` | 10 | Max pages per PDF |
| `max_pixels` | 50,000,000 | Max render pixels per page |
| `dpi` | 150 | Render DPI for pixel check |
| `max_compression_ratio` | 100 | Zip-bomb threshold |
| `max_zip_entries` | 10000 | Max ZIP entries per DOCX |
| `scan_enabled` | false | Enable malware scanning |
| `scan_engine` | "yara+cdr" | Scanner engine |
| `cdr_dpi` | 200 | CDR render DPI for PDF |
| `cdr_reconstruct_pdf` | true | Apply CDR to PDF |
| `cdr_reconstruct_docx` | true | Apply CDR to DOCX |

---

## Decision ADR-008: Test Coverage

**Status:** Implemented  
**Scope:** `tests/`

| File | Tests |
|------|-------|
| `tests/test_scanner.py` | 24 tests — magic byte, zip bomb, yara, CDR (full + targeted), clean passthrough, infected, external links (Informational), raw sha256, structural invalid, schema validation, legacy compat |
| `tests/test_s1_intake.py` | 21 tests — file type detection, safe filename, outcomes, version fields, cache hit, pipeline integration |
| `tests/test_pipeline.py` | 19 tests — clean/corrupt/oversized/injection, hash stability, cache hit, DOCX/text end-to-end, versions/timings, normal resume with metadata links (CLEAN), JavaScript PDF (QUARANTINE) |
| `tests/test_s2_verify.py` | 17 tests — font anomalies, injection, classification, verdict computation |
| `tests/test_s3_govern.py` | 3 tests — pre-gate clean, post-gate clean, post-gate quarantine |
| `tests/test_s4_structure.py` | 8 tests — sections, fields, date intervals, rule flags, labels, manipulation flags, JD track, sealed output |
| `tests/test_s5_normalise.py` | 4 tests — canonical skills, unknown skill, hash/seal, structure field changes report hash |
| `tests/test_seal.py` | 2 tests — seal roundtrip, deterministic fields |
| `tests/test_log_chain.py` | 3 tests — append_log chain, verify_chain true, verify_chain detects tampering (skipped without PostgreSQL) |

**Total: 100 tests (97 passed, 3 skipped without PostgreSQL).**

**Command:** `DATABASE_URL=postgresql://postgres:password@localhost:5432/egca PYTHONPATH=. .venv/bin/pytest`

---

## Decision ADR-009: Remaining Stubs / Known Gaps

| Stub | File | Status |
|------|------|--------|
| Stage 4.2 Latest-version check | `stages/s3_govern.py` | STUB — wire to external service |
| Stage 4.3 Job-open check | `stages/s3_govern.py` | STUB — wire to external service |
| Non-PDF Stage 2 support | `stages/s2_verify/__init__.py` | DONE — DOCX/text pass Stage 1 and reach Stages 3-5 via sanitized text |
| Malware scanner daemon deployment | `app/scanner.py` | scan_enabled defaults to false; set to true in production |
| YARA external_link rule for PDFs | `app/scanner.py` | Limited — compressed PDF streams hide URLs from string matching; external_link is Medium severity (stripped by CDR, not blocked) |
| Encrypted PDF detection | `app/scanner.py` | pikepdf PasswordError detection; non-PDF encrypted files not detected |
| Independent verifier (Level 1-3) | Not implemented | Section 4.5 — stub only |
| Data contracts (Section 10) | Not implemented | Section 10 — not started |

---

## Decision ADR-010: Rollback Considerations

If conditional CDR causes issues:
1. Set `scan_enabled=false` to bypass all scanning (reverts to pre-scanner behavior)
2. Set `cdr_reconstruct_pdf=false` and `cdr_reconstruct_docx=false` to skip CDR entirely
3. To restore universal CDR (old behavior), modify `scan_file()` to always call `cdr_reconstruct()` regardless of findings
4. To disable structural parse check, remove the `structural_parse_check()` call from `scan_file()`

If Stage 4 structure causes issues:
1. The `extract_structure()` replacement is fully backward-incompatible; pipeline gracefully falls back to empty `StructureResult` on exception
2. Set `track="resume"` default to disable JD-specific rules (J1-J3)

---

## Decision ADR-011: Stage 4 Structure — Replaced Thin Extractor with Full Spec-Compliant Implementation

**Status:** Implemented  
**Scope:** `stages/s4_structure.py`, `app/schemas.py`, `app/pipeline.py`, `stages/s5_normalise.py`

### Before (thin skeleton)
`extract_structure(clean_text, word_records)` returned `(List[Section], List[Field])` with:
- Linear `O(n*m)` word lookup via `_find_word_id()` (buggy with duplicate words)
- Only email/phone/date field extraction via regex
- Basic date consistency checks (future dates, end-before-start)
- No conservation ledger, no labels, no manipulation flags, no sealed output

### After (spec-compliant Stage 4)
`extract_structure(clean_text, word_records, track, uploaded_at)` returns `StructureResult` with:

| Feature | Spec Ref | Implementation |
|---------|----------|----------------|
| WordIndex O(1) lookup | 8.1 | `WordIndex` class replaces `_find_word_id()` |
| Section detection | 8.9 | Alias matching + line-based heuristics |
| Date intervals | 8.3 | `DateInterval` with start/end, `is_present` → `as_of` from `uploaded_at` |
| Labels | 8.4 | `CONTRADICTION`, `CONFLICT`, `FACT`, `NOT_EVALUATED` |
| Rule families | 8.4 | R1-R11, F1-F6, J1-J3 |
| Manipulation flags | 8.5 | M1-M5 from Stage 2 findings |
| Conservation ledger | 8.2 | Append-only `List[Dict]` audit entries |
| Sealed output | 8.8 | `record_root` (record_hash), `pii_ref` (SHA-256 of PII fields) |
| JD track | 8.6 | J1-J3 rules when `track="job_description"` |

### Optimizations
- `WordIndex`: `O(1)` text→word_id lookup vs `O(n*m)` linear scan
- `lookup()` (peek) vs `find()` (consume): prevents word double-consumption between section detection and field extraction
- Memoized date parsing: `_parse_date_cached()` avoids re-parsing duplicate date strings

---

## Decision ADR-012: Stage 5 Normalise — Integrated Structure Output

**Status:** Implemented  
**Scope:** `stages/s5_normalise.py`, `app/schemas.py`

`build_output()` now accepts optional `structure_result: StructureResult` and `clean_artifact_sha256`, populating all structure fields in `Phase1Output` and including them in `compute_report_hash()` so the seal attests to every piece of output data.

---

## Decision ADR-013: Single Audit Log — append_only_log is Canonical

**Status:** Implemented  
**Scope:** `app/log.py`, `app/db.py`, `scripts/init_db.py`

- `append_only_log` is the canonical audit store (BIGSERIAL, TIMESTAMPTZ, hash-chained entries)
- `governance_audit_log` is now a VIEW over `append_only_log` (backward compatible, no data deleted)
- `audit_insert()` writes through `append_log()` → `append_only_log`
- One-time backfill copies existing `governance_audit_log` rows into `append_only_log`
- Single-writer guard via `pg_advisory_xact_lock(hashtext('egca_log'))`
- `get_log_chain()` and `verify_chain()` work on PostgreSQL

---

## Decision ADR-014: Hash Chain Closure — block_hash + clean_artifact_sha256

**Status:** Implemented  
**Scope:** `stages/s2_verify/__init__.py`, `app/hash.py`, `app/schemas.py`, `app/pipeline.py`, `stages/s5_normalise.py`

- `block_hash()` computed per block using `app.hash.block_hash()` (domain tag `egca/block/v1`)
- `clean_artifact_sha256 = clean_hash([...block hashes...])` computed as hash chain root
- `clean_artifact_sha256` field added to `Phase1Output`
- Included in `compute_report_hash()` so the seal covers the hash chain

---

## Decision ADR-015: Single Source of Truth for Thresholds

**Status:** Implemented  
**Scope:** `app/config.py`, `config/config.yaml`, `stages/s3_govern.py`, `stages/s2_verify/verdict.py`

- `review_threshold` (2.0) and `quarantine_threshold` (5.0) moved to config
- `s3_govern.py` reads thresholds from `config.review_threshold` / `config.quarantine_threshold`
- `verdict.py` reads thresholds from `config` directly (no longer imports from s3_govern)
- `scan_poll_interval` and `scan_max_attempts` marked DEPRECATED (scanner runs synchronously)

---

## Decision ADR-016: Non-PDF Support End-to-End

**Status:** Implemented  
**Scope:** `app/pipeline.py`

- DOCX files: CDR extracts clean text → Stage 2 verify skipped (minimal CLEAN verdict) → Stages 3-5 process extracted text
- Text files: raw bytes used as clean text → same flow as DOCX
- `clean_artifact_sha256` computed even for non-PDF (hash of empty block list)
- Tests added for DOCX and .txt end-to-end pipeline

---

## Decision ADR-017: Scan Layer Provenance

**Status:** Implemented  
**Scope:** `app/scanner.py`, `app/schemas.py`, `stages/s1_intake.py`, `app/pipeline.py`

- `ScanFinding.scan_layer` field added: "raw"|"yara"|"structural"|"cdr"|"encryption"|"zip"
- Raw pre-scan blocks (archive bomb, suspicious PDF object) emit ScanFindings with `scan_layer`
- `scan_result_insert_full()` persists findings with layer info to `scan_results`
- Raw pre-scan layer preserved (not removed)

---

**Last Updated:** 2026-11-28  
**Total Tests:** 97 (94 passed, 3 skipped without PostgreSQL)
