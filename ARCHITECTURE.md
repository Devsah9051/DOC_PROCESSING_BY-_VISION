# EGCA Phase 1 — Architecture

EGCA Phase 1 turns a resume or job description PDF into verified, normalised,
signed, and traceable data. It does not judge candidates; it only detects,
verifies, and structures what is on the page.

## Pipeline Overview

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Stage 1   │────▶│   Stage 2    │────▶│   Stage 3   │────▶│   Stage 4    │────▶│   Stage 5   │
│   Intake    │     │    Verify    │     │   Govern    │     │   Structure  │     │  Normalise  │
└─────────────┘     └──────────────┘     └─────────────┘     └──────────────┘     └─────────────┘
       │                   │                   │                   │                   │
  file bytes          detected blocks     gate decision   structured record   normalised record
  + sha256            + clean text        + risk tier     + record_root       + stage5_root
                                                    + file_state_hash     + seal
```

| Stage | Responsibility | Key Output |
|-------|---------------|------------|
| **1. Intake** | Validate file, compute SHA-256, check cache, open PDF | `IntakeContext` (sha256, doc, cache_hit) |
| **2. Verify** | Detect hidden/manipulated text, render/ghost-diff/contrast, OCR fallback, verdict | `clean_text`, `verdict`, `block_records` |
| **3. Govern** | Pre-gate/post-gate decisions, suspicion rating, file state | `file_state`, `risk_tier`, `proceed` flag |
| **4. Structure** | Section detection, field extraction, conservation ledger | `sections`, `fields`, `record_root` |
| **5. Normalise** | Skill canonicalisation, taxonomy mapping, sealing | `tokens`, `stage5_root`, `signature` |

## Module Layout

```
EGCA Phase 1/
├── app/                          # Application layer (FastAPI + orchestration)
│   ├── main.py                   # FastAPI app: /health, /phase1 endpoints, lifespan
│   ├── config.py                 # Configuration loader (config.yaml → Config dataclass)
│   ├── db.py                     # PostgreSQL connection pool + cache/audit queries
│   ├── schemas.py                # Pydantic models (Phase1Output, Verdict, WordRecord, etc.)
│   ├── seal.py                   # Ed25519 signing (seal_fields, sign, verify)
│   ├── pipeline.py               # Pipeline orchestrator (run_phase1, 5-stage flow)
│   ├── hash.py                   # Canonical hashing + domain tags (Section 4.1)
│   └── log.py                    # Append-only audit log with hash chaining (Section 4.3)
├── stages/                       # Pipeline stages
│   ├── s1_intake.py              # Stage 1: file validation, hashing, cache check
│   ├── s2_verify/                # Stage 2: verification submodules
│   │   ├── __init__.py           # verify_pages() — main entry
│   │   ├── rules.py              # Cheap rules (tiny font, opacity, off-page, etc.)
│   │   ├── render.py             # Page rendering, ghost diff, contrast
│   │   ├── ocr.py                # OCR engine (PaddleOCR) + triggers
│   │   └── verdict.py            # Verdict computation (CLEAN/REVIEW/QUARANTINE)
│   ├── s3_govern.py              # Stage 3: pre-gate/post-gate, suspicion rating
│   ├── s4_structure.py           # Stage 4: section detection, field extraction
│   └── s5_normalise.py           # Stage 5: skill normalisation, sealing, cache write
├── config/                       # Configuration files
│   ├── config.yaml               # Pipeline parameters (DPI, thresholds, weights)
│   └── taxonomy.yaml             # Skills taxonomy (canonical skills + aliases)
├── scripts/                      # Utility scripts
│   ├── init_db.py                # Database schema initialization + TTL cleanup
│   └── setup_docker_postgres.sh  # Docker PostgreSQL setup (container + schema + .env)
├── tests/                        # Test suite (pytest)
│   ├── conftest.py               # Test fixtures (PDF generation, stubs)
│   ├── test_pipeline.py          # Integration tests (end-to-end pipeline)
│   ├── test_s2_verify.py         # Stage 2 unit tests (rules, render, verdict)
│   ├── test_s3_govern.py         # Stage 3 unit tests (govern, suspicion)
│   ├── test_s4_structure.py      # Stage 4 unit tests (structure extraction)
│   ├── test_s5_normalise.py      # Stage 5 unit tests (normalisation, sealing)
│   └── test_seal.py              # Seal/signature unit tests
├── docker-compose.yml            # Docker Compose (PostgreSQL 16)
├── pyproject.toml                # Python project metadata + dependencies
├── uv.lock                       # Locked dependency versions
├── .env.example                  # Environment variable template
├── .gitignore                    # Git ignore rules
├── ARCHITECTURE.md               # This document
└── README.md                     # Quick start + usage guide
```

## Stage Details

### Stage 1 — Intake (`stages/s1_intake.py`)

Validates the uploaded file before any processing:

1. **Size cap** — rejects files over `max_bytes` (default 10 MB)
2. **Filename safety** — rejects paths with `..` or unsafe characters
3. **PDF header** — verifies `%PDF-` magic bytes
4. **SHA-256 fingerprint** — computes `original_sha256` over exact file bytes
5. **Cache lookup** — checks `resume_cache` by `(sha256, pipeline_version, rules_version)`
6. **Open PDF** — uses PyMuPDF; rejects encrypted or corrupt documents
7. **Page limit** — enforces `max_pages` (default 10)
8. **Pixel limit** — enforces `max_pixels` per page at configured DPI

Returns an `IntakeContext` with the document handle, SHA-256, and cache status.

### Stage 2 — Verify (`stages/s2_verify/`)

Core verification layer. Runs deterministic checks before any heavy models:

**Detection (D0) — per word:**
- Invisible render mode (text rendering mode 3)
- Tiny font (below `tiny_font_max_pt`, default 6pt)
- Off-page position (bbox outside page rect)
- Near-zero opacity (alpha < 0.02)
- Covered by drawn shape (white rect over text → `COVERED_BY_SHAPE`)

**Detection (D1) — ghost diff:**
- Render page with and without text layer at pinned DPI
- Subtract renders; compute ink share in word crops
- Words where ink remains after erasure → `NOT_VISIBLE`

**Contrast:**
- Luminance contrast ratio: `(L1 + 0.05) / (L2 + 0.05)`
- Background read from ghost-diff (text-erased) image
- Below `contrast_min` (default 1.5) → `LOW_CONTRAST`

**OCR triggers (two only):**
1. Scanned page (no usable text layer) → full-page OCR, words marked `OCR_ONLY`
2. Anomaly (ghost-diff failure, contrast failure, odd font map) → OCR on flagged boxes only

**Verdicts:**
- `CORROBORATED` — text layer + visible on render
- `CORROBORATED_FUZZY` — small render differences (ligatures, accents)
- `UNCORROBORATED_NOT_VISIBLE` — in text layer, not visible → dropped
- `UNCORROBORATED_TEXT_MISMATCH` — visible, reads differently → REVIEW
- `ICON_GLYPH` — symbol/font icon → ignored
- `OCR_ONLY` — read by OCR only (scanned pages)
- `TEXT_SOURCE` — plain text file, not visually checked

**Final verdict:**
- Strong injection pattern → `QUARANTINE`
- Weighted score ≥ quarantine threshold → `QUARANTINE`
- Weighted score ≥ review threshold → `REVIEW`
- Otherwise → `CLEAN`

### Stage 3 — Govern (`stages/s3_govern.py`)

Decides twice — before and after parsing:

**Pre-gate (before Stage 2):**
- Idempotency key: `SHA-256(egca/idem/v1 + 0x00 + version_id + ":" + parser_build_id)`
- Epoch fencing via `version_seq`; older versions → `SUPERSEDED`
- State watcher: closed job / withdrawn application → `ARCHIVED_INACTIVE`
- Result cache hit → reuse stored result

**Post-gate (after Stage 2):**
- Universal injection scan on all text (visible + hidden + side channel)
- Suspicion rating: sum of finding weights by severity
- Final risk tier: CLEAN / REVIEW / QUARANTINE
- Early stop: QUARANTINE does not proceed to Stage 4

### Stage 4 — Structure (`stages/s4_structure.py`)

Builds a structured record from clean text:

- **Section detection** — heading aliases + layout + position + content shape signals
- **Field extraction** — email, phone, date via regex; each with `word_ids` and `bbox`
- **Conservation ledger** — every verified character placed in a field or listed as unplaced
- **Labels** — CONTRADICTION, CONFLICT, FACT, NOT_EVALUATED
- **Manipulation flags** — M1-M5 (instruction-like, wrong document, stuffing, unicode anomaly, link mismatch)

### Stage 5 — Normalise (`stages/s5_normalise.py`)

Canonicalises and seals:

- **Term normaliser** — exact match → alias match → fuzzy match (rapidfuzz ≥85)
- **Negative pairs** — keep lookalikes apart (Java/JavaScript, C/C#)
- **Provenance tags** — STATED, NORMALIZED, PROPOSED_AGREED, INFERRED
- **Status** — PRESENT, UNMAPPED, NOT_ACCEPTED, MISSING
- **Skill relations** — same family/ecosystem, prerequisite, etc.
- **Seal** — Ed25519 signature over `stage5_root` + `file_state_hash` + versions

## Trust & Sealing (Section 4)

### Hash Chain

```
original_sha256  →  block_hash  →  clean_artifact_sha256  →  record_root  →  stage5_root  →  file_state_hash  →  seal
   (Stage 1)         (Stage 2)          (Stage 2)            (Stage 4)         (Stage 5)         (Stage 3/5)     (Sealer)
```

### Domain Tags

All hashes use the format `SHA-256(tag + 0x00 + canonical_bytes)`:

| Tag | Purpose |
|-----|---------|
| `egca/block/v1` | Per-block hash (Stage 2) |
| `egca/clean/v1` | Clean artifact hash (Stage 2) |
| `egca/record/v1` | Structured record root (Stage 4) |
| `egca/norm/v1` | Normalised record root (Stage 5) |
| `egca/state/v1` | File state hash (Stage 3/5) |
| `egca/log/v1` | Append-only log entry hash |
| `egca/idem/v1` | Idempotency key |

### Append-Only Log (`app/log.py`)

Entry kinds: `GATE_DECISION`, `SEAL`, `FILE_STATE_UPDATE`, `HUMAN_DECISION`, `TOMBSTONE`, `CHECKPOINT`

Each entry is hash-chained to the previous entry. Single writer with DB lock.

### Independent Verifier

Three levels:
1. **Level 1 Integrity** — check signature, recompute all roots, verify effective tier
2. **Level 2 Reproduce** — re-run Stages 4-5 deterministically, compare roots
3. **Level 3 Re-read** — re-run Stage 2 on original, compare `clean_artifact_sha256`

## Data Flow

```
Upload (PDF) 
  │
  ▼
Stage 1: Intake ──┬── cache hit? ──┬── return cached output
  │               └── no           │
  │                                ▼
  │                    Stage 2: Verify ──┬── QUARANTINE? ──┬── Stage 3 post-gate ── STOP
  │                                      └── proceed      └── proceed           │
  │                                                                             ▼
  │                                Stage 3: Govern ── pre-gate ──┬── stop? ──┐
  │                                                              └── proceed   │
  │                                                                             ▼
  │                                Stage 4: Structure ── sections + fields ──┐
  │                                                                             ▼
  │                                Stage 5: Normalise ── tokens + seal ──────┤
  │                                                                             ▼
  │                                                       Phase1Output ◀──────┤
  │                                                             (signed, sealed)
  │
  ▼
Part II (downstream) receives verified, normalised, traceable data
```

## Configuration

All pipeline parameters live in `config/config.yaml`:

| Setting | Default | Description |
|---------|---------|-------------|
| `dpi` | 150 | Render DPI |
| `max_bytes` | 10,000,000 | Max file size |
| `max_pages` | 10 | Max pages per PDF |
| `max_pixels` | 50,000,000 | Max render pixels per page |
| `contrast_min` | 1.5 | WCAG contrast threshold |
| `min_ink` | 0.02 | Min ink share for NOT_VISIBLE |
| `ghost_diff_threshold` | 40 | Ghost diff threshold |
| `ocr_margin` | 4 | Margin around word crops |
| `iou_threshold` | 0.30 | OCR/text IoU match threshold |
| `fuzzy_threshold` | 85 | Fuzzy match threshold |
| `suspicious_score` | 5.0 | Review threshold |
| `audit_rate` | 0.05 | Audit sample rate |
| `tiny_font_max_pt` | 6.0 | Tiny font threshold |

## Quick Start

```bash
# 1. Setup PostgreSQL via Docker (recommended)
./scripts/setup_docker_postgres.sh

# 2. Or use local PostgreSQL
psql -c "CREATE DATABASE egca;"
python scripts/init_db.py

# 3. Set environment variables
cp .env.example .env
# Edit .env with your DATABASE_URL and SEAL_KEY

# 4. Install dependencies
uv sync

# 5. Run tests
uv run pytest

# 6. Run server
uv run app/main.py
```

## Testing

```bash
# Full test suite
uv run pytest

# Specific stage tests
uv run pytest tests/test_s2_verify.py
uv run pytest tests/test_s3_govern.py
uv run pytest tests/test_s4_structure.py
uv run pytest tests/test_s5_normalise.py
uv run pytest tests/test_seal.py

# Pipeline integration tests
uv run pytest tests/test_pipeline.py
```

All 41 tests pass with the Docker PostgreSQL setup.
