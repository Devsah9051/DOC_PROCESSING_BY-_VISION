# Stage 1: Intake

Validates uploaded PDF files before any processing.

## Responsibilities
- Enforce max file size (10 MB default)
- Validate safe filename characters
- Verify `%PDF-` header magic bytes
- Compute SHA-256 of file bytes
- Check cache by `(sha256, pipeline_version, rules_version)`
- Open PDF with PyMuPDF; reject encrypted/corrupt documents
- Enforce max_pages (10) and max_pixels per page at 150 DPI

## Entry Point
`intake(file_bytes, filename, upload_id, cfg)` → `IntakeContext`

## Spec Coverage
See `checkpoints/stage1_intake.md` for full spec gap analysis.
