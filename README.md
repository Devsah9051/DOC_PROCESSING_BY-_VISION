# EGCA Phase 1

## Title + one line
Phase 1 turns a resume or JD PDF into verified, normalised, signed, traceable data. It does not judge candidates.

## Principles
Copy what the page shows; every item traces to page + bbox; no AI writes any data; hidden text is flagged, never deleted.

## Pipeline
one line per stage (Intake, Verify, Govern, Structure, Normalise). Stage 1 Intake now includes a synchronous 4-stage malware scan + CDR pipeline (magic-byte → zip-bomb → yara → CDR) that produces a SanitizedArtifact safe for OCR/LLM consumption.

## Scanner (Stage 1, Section 5.2)
Conditional scanner pipeline applied to every upload with 4 edge case fixes:

1. **Magic-Byte Check** — rejects spoofed extensions / non-PDF & non-DOCX binaries
2. **Encryption Check** — rejects password-protected/corrupt PDFs (422) before YARA can't see inside
3. **Zip-Bomb Guard** — rejects recursive/oversized DOCX archives & path traversal
4. **yara-python scan** — refined severity: High (/JS, /JavaScript, /OpenAction, /AA, /Launch, /RichMedia, /EmbeddedFile, /XFA, VBA macros, DDEAUTO) → BLOCKED; Medium (/Metadata, /AcroForm, /Annotations, external links, DOCX custom props) → targeted sanitization
5. **Structural Parse Check** — pikepdf/pymupdf for PDF, defusedxml for DOCX; runs even on no-findings branch; corrupt files → BLOCKED
6. **CDR Reconstruction (conditional)** — applied ONLY when YARA Medium findings exist; clean files skip CDR entirely, preserving text layer for Stage 2 fast path

Output: `SanitizedArtifact` (sha256, raw_sha256 immutable hash, file_type, sanitized_bytes, findings, cdr_applied, cdr_method). When `cdr_applied=False`, the original text layer is preserved for fast-path extraction in Stage 2. Raw bytes stored separately for audit/forensics.

## Verify flow
fast path (PyMuPDF rules, Ghost Diff, contrast) vs OCR path (the 4 triggers from step 3.7). Stage 3 pre-gate/post-gate consume Stage 1 scan findings for suspicion rating.

## Quick start
```bash
# Requirements
uv sync

# Init DB (requires local PostgreSQL)
psql -c "CREATE DATABASE egca;"
python scripts/init_db.py

# Set env
echo 'DATABASE_URL=postgresql://postgres:postgres@localhost:5432/egca' > .env
echo 'SEAL_KEY=$(python -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; import base64; print(base64.b64encode(Ed25519PrivateKey.generate().private_bytes_raw()).decode())">' >> .env

# Run server
uv run app/main.py

# Run tests
uv run pytest

# Run benchmark
python scripts/benchmark.py
```

## Config
| Setting | Default | Description |
|---------|---------|-------------|
| dpi | 150 | Render DPI |
| max_bytes | 10000000 | Max file size (10 MB) |
| max_pages | 10 | Max pages per PDF |
| max_pixels | 50000000 | Max render pixels per page |
| max_compression_ratio | 100 | ZIP bomb compression ratio threshold |
| max_zip_entries | 10000 | Max ZIP entries per DOCX |
| scan_enabled | false | Enable malware scanning |
| scan_engine | yara+cdr | Scanner engine (yara+cdr) |
| cdr_dpi | 200 | CDR render DPI for PDF |
| cdr_reconstruct_pdf | true | Apply CDR to PDF files |
| cdr_reconstruct_docx | true | Apply CDR to DOCX files |
| contrast_min | 1.5 | WCAG contrast threshold |
| min_ink | 0.02 | Min ink share for NOT_VISIBLE |
| suspicious_score | 5.0 | Score threshold for SUSPICIOUS |
| audit_rate | 0.05 | Audit sample rate |
| pipeline_version | 1.0.0 | Pipeline version |
| rules_version | 1.0.0 | Rules version |

## Output: Phase1Output fields and the 3 statuses

| Field | Description |
|-------|-------------|
| sections | Detected document sections |
| tokens | Verified word records in reading order |
| verdict.status | CLEAN / SUSPICIOUS / QUARANTINED |
| verdict.score | Weighted rule score |
| verdict.rules | List of rule IDs that fired |
| verdict.reasons | Human-readable reasons |
| versions | pipeline_version, rules_version |
| timings_ms | Per-stage timing in ms |
| prev_hash | sha256 of previous file |
| report_hash | sha256 of canonical output |
| signature | Ed25519 signature |

**3 statuses:**
- **CLEAN** — no issues found
- **SUSPICIOUS** — weighted score above threshold, no strong injection
- **QUARANTINED** — strong injection detected or fatal error

## Project layout
```
EGCA WORKING/
├── config/              ← config.yaml, taxonomy.yaml
├── app/                ← main.py, config.py, schemas.py, db.py, seal.py, pipeline.py, scanner.py
├── stages/             ← s1_intake.py, s2_verify/ (rules, render, ocr, verdict), s3_govern.py, s4_structure.py, s5_normalise.py
├── tests/              ← conftest.py, test_pipeline.py, test_s1_intake.py, test_s2_verify.py, test_s3_govern.py, test_s4_structure.py, test_s5_normalise.py, test_scanner.py, test_seal.py
├── scripts/            ← init_db.py, benchmark.py
├── .env.example
├── pyproject.toml
└── README.md
```

## Results
See test output from step 7. Performance varies with hardware and PDF content. Fast path (no OCR) typically under 1 s per resume; OCR path depends on model download and page count.

## Limitations
- Stubs in stages 4.2 and 4.3 (latest-version check, job-open check) not yet wired to external services
- Thresholds tuned on synthetic fixtures only; real-world performance may vary
- Remapped-glyph risk in fast mode (text with custom fonts may not be detected)
- Personal-data retention: resumes stored in audit log; TTL cleanup recommended via `python scripts/init_db.py --cleanup`
- PaddleOCR model download required for OCR path (first run may be slow)
- CDR PDF reconstruction renders at 200 DPI which may increase file size for image-heavy documents; text layer is destroyed (image-only output)