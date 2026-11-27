# Stage 1: Intake

Validates uploaded files before any processing.

## Responsibilities
- Enforce max file size (10 MB default)
- Validate safe filename characters
- Magic-Byte Check: verify `%PDF-`, `PK` (DOCX), or valid UTF-8 text; reject spoofed extensions
- Zip-Bomb Guard: reject recursive/oversized DOCX archives & path traversal
- Compute SHA-256 of file bytes
- Check cache by `(sha256, pipeline_version, rules_version)`
- yara-python scan: detect embedded JS, auto-actions, VBA macros, DDE, external links
- CDR Reconstruction (conditional): only applied when YARA finds threats
  - Clean files → skip CDR, original bytes preserved, text layer intact
  - Medium findings → targeted sanitization
  - High findings → BLOCKED
- Open PDF with PyMuPDF; reject encrypted/corrupt documents
- Enforce max_pages (10) and max_pixels per page at 150 DPI
- Register version in version_registry (compare-and-swap)

## Entry Point
`intake(file_bytes, filename, upload_id, cfg)` → `IntakeContext` (includes `sanitized_artifact` and `scan_findings`)

## Outcomes
- **READY** — passed all checks; `cdr_applied=False` means text layer intact for fast path
- **DUPLICATE** — cache hit, previously processed
- **REJECTED** — unsafe filename, oversized, unsupported type, corrupt/encrypted PDF, too many pages
- **BLOCKED** — zip bomb, suspicious PDF object, YARA High threat detected, scan infection
- **FAILED** — version registration error
- **EXPIRED** — version registration failed

## Spec Coverage
See `checkpoints/stage1_intake.md` for full spec gap analysis.
