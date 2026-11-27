# Stage 1: Intake — Checkpoint Log

## Overview
**File:** `stages/s1_intake.py`
**Pipeline Role:** Entry point for file uploads — validates file integrity, runs synchronous scanner pipeline with conditional CDR, checks cache, opens document, enforces size/page/pixel limits.
**Dependents:** `app/pipeline.py:run_phase1()`, `app/db.py:cache_get()`, `app/scanner.py`

---

## Purpose
- Enforce max file size (10 MB default)
- Validate safe filename characters
- **Magic-Byte Check**: verify `%PDF-`, `PK` (DOCX), or valid UTF-8 text; reject spoofed extensions
- **Encryption Check**: detect password-protected/corrupt PDFs via pikepdf (422) before YARA can't see inside
- **Zip-Bomb Guard**: reject recursive/oversized DOCX archives & path traversal
- Compute SHA-256 of file bytes
- Check cache (sha256 + pipeline_version + rules_version)
- **yara-python scan**: detect embedded JS, auto-actions, VBA macros, DDE, external links (refined severity)
- **Structural Parse Check**: pikepdf+pymupdf for PDF, defusedxml for DOCX — runs even on no-findings branch
- **CDR Reconstruction (conditional)**: applied ONLY when YARA finds Medium findings
  - Clean files → skip CDR, original bytes preserved, text layer intact
  - Medium findings → targeted sanitization (strip PDF Metadata/AcroForm/Annotations; DOCX → clean text)
  - High findings → BLOCKED (never strip)
- Open PDF with PyMuPDF; reject encrypted/corrupt documents
- Enforce max_pages (10) and max_pixels (50M per page at 150 DPI)
- Register version in version_registry (compare-and-swap)
- Return `IntakeContext` with sanitized_artifact (including raw_sha256) + scan_findings for downstream stages

---

## Current State

### Code Structure
```python
@dataclass
class IntakeContext:
    outcome: str              # READY, DUPLICATE, REJECTED, BLOCKED, FAILED, EXPIRED
    sha256: str
    size_bytes: int
    filename: str
    file_type: str            # pdf, docx, text, unknown
    track: str                # resume, job_description
    version_id: str
    version_seq: int
    uploaded_at: float
    quarantine_pointer: Optional[str] = None
    page_count: int = 0
    encrypted: bool = False
    cache_hit: bool = False
    cached_output: Optional[dict] = None
    doc: object | None = None
    reason: str = ""
    # Scanner output (Section 5.2 — synchronous scan + conditional CDR)
    sanitized_artifact: Optional[SanitizedArtifact] = None
    scan_findings: list[ScanFinding] = field(default_factory=list)


@dataclass
class ScanFinding:
    rule_id: str
    stage: str                # "magic", "zip", "yara", "cdr", "structural", "encryption"
    severity: str             # "High", "Medium", "Low", "Informational"
    description: str
    matched_strings: list[str]


@dataclass
class SanitizedArtifact:
    sha256: str
    raw_sha256: str           # Immutable hash of original upload (audit/forensics)
    file_type: str
    original_size: int
    sanitized_size: int
    sanitized_bytes: bytes    # Safe for OCR/LLM consumption
    scan_engine: str          # "yara+cdr"
    infected: bool
    threat_name: Optional[str]
    findings: list[ScanFinding]
    cdr_applied: bool
    cdr_method: Optional[str]
    sanitized_artifact_uri: Optional[str]  # Derived artifact storage URI
    scanned_at: float
```

### Key Functions (in `app/scanner.py`)
- `magic_byte_check(file_bytes)` — validates %PDF-, PK, UTF-8 text; returns (file_type, finding, encryption_reason)
- `encryption_check(file_bytes, file_type)` — pikepdf PasswordError detection; rejects encrypted/corrupt PDFs
- `zip_bomb_guard(file_bytes, file_type, cfg)` — DOCX ZIP compression ratio + path traversal
- `yara_scan(file_bytes)` — embedded JS, VBA macros, DDE, external links, PDF annotations (refined High/Medium severity)
- `structural_parse_check(file_bytes, file_type)` — pikepdf+pymupdf for PDF, defusedxml for DOCX; runs even on no-findings
- `cdr_reconstruct_pdf_targeted(file_bytes)` — targeted PDF sanitization (strips /Metadata, /AcroForm, /Annotations), preserves text layer
- `cdr_reconstruct_pdf_full(file_bytes, dpi)` — full CDR (PDF → 200 DPI images), fallback when targeted fails
- `cdr_reconstruct_docx(file_bytes)` — DOCX → clean text (strips VBA/DDE/embeds/custom props)
- `scan_file(file_bytes, cfg)` — scanner pipeline with conditional CDR + structural parse + encryption check
- `intake(file_bytes, filename, upload_id, cfg)` — main entry; returns IntakeContext

### Applied Patches
- `app/scanner.py`: NEW — scanner pipeline with 4 edge case fixes (encryption, structural parse, raw_sha256, refined YARA severity)
- `app/scanner.py`: `cdr_reconstruct_pdf_targeted()` — targeted PDF sanitization preserving text layer
- `app/scanner.py`: `cdr_reconstruct_pdf_full()` — full CDR fallback (renders to images)
- `app/schemas.py`: Added `raw_sha256`, `sanitized_artifact_uri` to `SanitizedArtifact` model
- `app/config.py`: Added `scan_engine`, `cdr_dpi`, `cdr_reconstruct_pdf`, `cdr_reconstruct_docx`
- `config/config.yaml`: Added scanner + CDR config section
- `stages/s1_intake.py`: Integrated synchronous scan + CDR; added `sanitized_artifact`/`scan_findings` to IntakeContext
- `app/pipeline.py`: Reopens doc from sanitized_bytes when cdr_applied=True; keeps original doc when cdr_applied=False (fast path)
- `stages/s3_govern.py`: `govern_pre`/`govern_post` accept `scan_findings` + `cdr_applied` for suspicion rating
- `app/db.py`: Added `scan_result_insert_full()` for extended scan result persistence
- `scripts/init_db.py`: Updated scan_results table comment
- Removed: `scripts/run_scanner.py`, clamav dependency, async outbox scan flow, `zip_bomb_ratio_high` YARA rule (false positive)

---

## Refined YARA Severity Classification

| Severity | Rules | Action |
|----------|-------|--------|
| **High** | `/JavaScript`, `/JS`, `/OpenAction`, `/AA`, `/Launch`, `/RichMedia`, `/EmbeddedFile`, `/XFA`, `vbaProject.bin`, `DDEAUTO`, `PasswordError` | BLOCKED → QUARANTINE (never strip) |
| **Medium** | `/Metadata`, `/AcroForm` (non-XFA), `/Annotations`, external links (`http://`, `https://`, `file://`), `docProps/custom.xml` | Targeted sanitization (CDR applied) |
| **None** | No YARA matches | Skip CDR — original bytes preserved, text layer intact |

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
| `max_compression_ratio` | 100 | Zip-bomb (DOCX ZIP) |
| `max_zip_entries` | 10000 | Zip-bomb (DOCX ZIP) |
| `scan_enabled` | false | Enable malware scanning |
| `scan_engine` | "yara+cdr" | Scanner engine |
| `cdr_dpi` | 200 | CDR render DPI for PDF |
| `cdr_reconstruct_pdf` | true | Apply CDR to PDF |
| `cdr_reconstruct_docx` | true | Apply CDR to DOCX |

---

## Test Coverage
**File:** `tests/test_s1_intake.py` (21 tests)
- `test_detect_pdf/docx/text/unknown` — file type detection from magic bytes
- `test_safe_filename_valid/invalid` — filename safety validation
- `test_intake_clean_pdf_ready` — valid PDF → READY
- `test_intake_clean_pdf_jd_track` — job_description track detection
- `test_intake_corrupt_pdf_rejected` — corrupt PDF → REJECTED
- `test_intake_unsafe_filename_rejected` — unsafe filename → REJECTED
- `test_intake_oversized_pdf_rejected` — oversized page → REJECTED
- `test_intake_docx_ready` — valid DOCX → READY
- `test_intake_docx_archive_bomb_blocked` — archive bomb DOCX → BLOCKED
- `test_intake_docx_unsafe_filename_rejected` — unsafe DOCX filename → REJECTED
- `test_intake_text_ready` — plain text → READY
- `test_intake_not_a_pdf_rejected` — unsupported binary → REJECTED
- `test_intake_pdf_with_javascript_blocked` — PDF with /JavaScript → BLOCKED
- `test_intake_version_fields` — version_id, version_seq, populated
- `test_intake_cache_hit_duplicate` — cache hit → DUPLICATE
- `test_pipeline_rejected_intake_failed` — REJECTED → FAILED in pipeline
- `test_pipeline_blocked_intake_quarantine` — BLOCKED → QUARANTINE in pipeline

**File:** `tests/test_scanner.py` (20 tests)
- `TestMagicByteCheck` — pdf/text/unknown detection
- `TestZipBombGuard` — clean docx, path traversal, bad zip
- `TestYaraScan` — EICAR detection, clean file
- `TestCDR` — PDF reconstruction (full), DOCX text extraction
- `TestScanFile` — clean PDF artifact (cdr_applied=False, raw_sha256 preserved), EICAR infected, clean text passthrough, text with external links (Medium), structural invalid PDF blocked
- `TestScanFindingSchema` / `TestSanitizedArtifactSchema` — schema validation (incl. raw_sha256)
- `TestScanStubCompat` — legacy scan_stub/scan_clamav compatibility

**File:** `tests/test_pipeline.py` (integration)
- `test_cache_hit_returns_cached` — DUPLICATE returns cached output

---

## Known Issues & Remaining Tasks

| Issue | Severity | Details | Fix Needed |
|-------|----------|---------|------------|
| DB pool dependency | HIGH | `intake()` calls `cache_get()`/`get_version()`/`register_version()` which require DB pool initialized | Ensure `create_pool()` called in FastAPI lifespan before any request |
| CDR PDF output size | MEDIUM | 200 DPI rendering may increase file size for image-heavy docs when CDR applied; text layer destroyed for sanitized PDFs | Monitor output sizes; only applied when YARA finds threats (most clean files skip CDR) |
| Non-PDF Stage 2 support | MEDIUM | DOCX/text files pass Stage 1 but Stage 2 verify requires pymupdf doc | Pipeline returns FAILED for non-PDF; Stage 2 support pending |
| Cache hit validation | MEDIUM | Cached output returned without re-validating schema | Consider validating cached output schema on cache hit |
| scan_enabled defaults to false | LOW | Malware scanning disabled by default | Set scan_enabled=true in production |
| YARA external_link rule limited for PDFs | LOW | YARA scans raw bytes; compressed PDF streams hide URLs from string matching | Consider decompressing PDF streams before YARA scan, or accept limitation |
| Encrypted non-PDF files | LOW | pikepdf only detects PDF encryption; encrypted ZIP/DOCX not detected at intake | Consider format-specific encryption detection |

### Spec Gaps (Section 5) — RESOLVED
| Spec Ref | Requirement | Status |
|----------|-------------|--------|
| 5.1-5.2 | Accept resume or JD (PDF) | Complete |
| 5.1-5.2 | Accept DOCX/plain text | Complete (detection only; parsing in later stages) |
| 5.2 | File type from first bytes (%PDF-, PK, valid text) | Complete |
| 5.2 | Size and page limits | Complete |
| 5.2 | Encryption check | Complete |
| 5.2 | Archive bomb detection | Complete (DOCX ZIP compression ratio) |
| 5.2 | PDF object tree scan for /JS, /JavaScript, etc. | Complete (yara-python rules with refined severity) |
| 5.2 | Malware scan through scanner daemon | Complete (synchronous yara+cdr pipeline in Stage 1) |
| 5.2 | Fingerprint: original_sha256 | Complete |
| 5.3 | Version registry with CAS | Complete (DB-backed, compare-and-swap insert) |
| 5.3 | Transactional outbox | Replaced by synchronous scan; outbox retained for other events |
| 5.3 | Outcomes: READY, DUPLICATE, REJECTED, BLOCKED, FAILED, EXPIRED | Complete |
| 5.4 | Output: version_id, version_seq, original_sha256, file type, size, uploaded_at, track, outcome, quarantine_pointer | Complete |

---

## Next Steps
1. Set `scan_enabled=true` in production config
2. Monitor CDR output sizes and scan latency
3. Implement Stage 2 support for DOCX/plain text file types
4. Add metrics for cache hit rate and scan throughput

---

## Relevant File Links
- `stages/s1_intake.py` — Stage 1 implementation (includes scanner integration)
- `app/scanner.py` — Scanner pipeline (magic-byte, encryption, zip-bomb, yara, structural parse, conditional CDR)
- `app/db.py` — `cache_get()`, `get_version()`, `register_version()`, `scan_result_insert_full()`
- `app/pipeline.py` — calls `intake()`, handles outcomes, uses sanitized_artifact
- `stages/s3_govern.py` — `govern_pre()`/`govern_post()` consume scan_findings + cdr_applied
- `app/config.py` — intake + scanner config keys
- `scripts/init_db.py` — version_registry, scan_results schema
- `config/config.yaml` — intake + scanner config values
- `tests/test_s1_intake.py` — Stage 1 unit tests (21 tests)
- `tests/test_scanner.py` — Scanner unit tests (20 tests)
- `tests/conftest.py` — DB stubs including scan_result functions

---

## Checkpoint Status
**Status:** OPERATIONAL — spec Section 5 gaps resolved (all implemented except non-PDF Stage 2 support)
**Last Verified:** 2026-11-27 — All 84 tests pass (20 scanner + 21 Stage 1 + 43 existing)
**Next Review:** When Stage 1 is integrated with Stage 2 for non-PDF file types