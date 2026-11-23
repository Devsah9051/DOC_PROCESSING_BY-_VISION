# EGCA Phase 1

## Title + one line
Phase 1 turns a resume or JD PDF into verified, normalised, signed, traceable data. It does not judge candidates.

## Principles
Copy what the page shows; every item traces to page + bbox; no AI writes any data; hidden text is flagged, never deleted.

## Pipeline
one line per stage (Intake, Verify, Govern, Structure, Normalise).

## Verify flow
fast path (PyMuPDF rules, Ghost Diff, contrast) vs OCR path (the 4 triggers from step 3.7).

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
├── app/                ← main.py, config.py, schemas.py, db.py, seal.py, pipeline.py
├── stages/             ← s1_intake.py, s2_verify/ (rules, render, ocr, verdict), s3_govern.py, s4_structure.py, s5_normalise.py
├── tests/              ← conftest.py, test_pipeline.py, test_s2_verify.py, test_s3_govern.py, test_s4_structure.py, test_s5_normalise.py, test_seal.py
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