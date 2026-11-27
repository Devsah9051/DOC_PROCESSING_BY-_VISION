# Query & Answer Log

## Format: Query | Answer | Stage | Relevant File Links

**Stage values:**
- `Stage 1: Intake` — `stages/s1_intake.py` (file validation, hashing, cache check)
- `Stage 2: Verify` — `stages/s2_verify/` (rules, render, ocr, verdict)
- `Stage 3: Govern` — `stages/s3_govern.py` (pre-gate/post-gate, suspicion rating)
- `Stage 4: Structure` — `stages/s4_structure.py` (section detection, field extraction)
- `Stage 5: Normalise` — `stages/s5_normalise.py` (taxonomy, canonicalization, sealing)
- `App Layer` — `app/` (db, pipeline, schemas, seal, hash, log, main, config)
- `GLOBAL` — Project setup, docs, configuration, CI/CD, not tied to a specific stage

**Maintenance rules:**
1. Every query made in this project folder must be logged here.
2. Always consult `README.md` and the relevant `checkpoints/*.md` before answering.
3. Fill in the `Stage` column for every entry; use `GLOBAL` for cross-cutting or non-stage queries.
4. Keep `Relevant File Links` accurate and pointing to actual files in the repo.
5. When starting a new chat session in this folder, read this file first to maintain continuity.

| Query | Answer | Stage | Links |
|-------|--------|-------|-------|
| Make EGCA DOC processing project operational | Set up venv, created `.env` with DATABASE_URL + SEAL_KEY, initialized PostgreSQL `egca` database, applied 13 code patches across 10 files, verified FastAPI `/health` endpoint | GLOBAL | `pyproject.toml`, `.env`, `scripts/init_db.py`, `stages/s2_verify/render.py`, `stages/s2_verify/__init__.py`, `stages/s2_verify/verdict.py`, `stages/s2_verify/rules.py`, `stages/s5_normalise.py`, `app/pipeline.py`, `app/db.py`, `app/schemas.py`, `stages/s4_structure.py` |
| Apply all patches + create maintenance checklist | All 13 patches applied; created `MAINTENANCE_CHECKLIST.md` and `QUERY_LOG.md` | GLOBAL | `MAINTENANCE_CHECKLIST.md`, `QUERY_LOG.md` |
| Create per-stage deep checkpoint logs | Created 6 checkpoint files: checkpoints/stage1_intake.md, checkpoints/stage2_verify.md, checkpoints/stage3_govern.md, checkpoints/stage4_structure.md, checkpoints/stage5_normalise.md, checkpoints/app_layer.md | GLOBAL | `checkpoints/*.md` |
| Align with EGCA Phase 1 Final Spec rev4 | Read full spec (2926 lines). Identified ~200+ gaps across all sections. Created SPEC_COMPLIANCE_CHECKLIST.md tracking every spec requirement vs current code. Updated all 6 checkpoints with spec gaps sections. | GLOBAL | `SPEC_COMPLIANCE_CHECKLIST.md`, `QUERY_LOG.md`, `checkpoints/*.md` |
| Fix all 41 tests to pass | Fixed status names (QUARANTINED→QUARANTINE, SUSPICIOUS→REVIEW), added pre-gate/post-gate split, fixed FileState validation, fixed hash determinism (excluded timings_ms), fixed COVERED_BY_SHAPE rule for covered text, added \u00b7 to ZERO_WIDTH chars for PyMuPDF conversion, fixed off_page fixture bbox | GLOBAL | `tests/test_pipeline.py`, `tests/test_s2_verify.py`, `tests/test_s3_govern.py`, `tests/conftest.py`, `stages/s2_verify/rules.py`, `stages/s2_verify/verdict.py`, `stages/s3_govern.py`, `stages/s5_normalise.py`, `app/pipeline.py` |
| Implement Section 4 hash chain & sealing | Created `app/hash.py` (domain tags, canonical hashing), `app/log.py` (append-only log), updated `app/seal.py` (stage5_root + file_state_hash signing), updated `app/schemas.py` (FileState, new statuses), updated `app/pipeline.py` (pre-gate/post-gate, hash chain flow) | App Layer | `app/hash.py`, `app/log.py`, `app/seal.py`, `app/schemas.py`, `app/pipeline.py` |
| Add Docker PostgreSQL setup command | Created `docker-compose.yml` (postgres:16-alpine, port 5432, creds postgres/password), `scripts/setup_docker_postgres.sh` (brings up container, initializes schema via `scripts/init_db.py`, writes `.env` with DATABASE_URL + SEAL_KEY). All 41 tests pass with Docker PostgreSQL. | GLOBAL | `docker-compose.yml`, `scripts/setup_docker_postgres.sh`, `scripts/init_db.py`, `.env` |
| Clean project and restore documentation | Removed redundant tracked/untracked files, created ARCHITECTURE.md, restored all checkpoint/query/maintenance files, updated .gitignore, pushed to GitHub | GLOBAL | `ARCHITECTURE.md`, `.gitignore`, `MAINTENANCE_CHECKLIST.md`, `QUERY_LOG.md`, `SPEC_COMPLIANCE_CHECKLIST.md`, `checkpoints/*.md` |
| Add Stage column to query log + define stage types | Added `Stage` column with values: Stage 1: Intake, Stage 2: Verify, Stage 3: Govern, Stage 4: Structure, Stage 5: Normalise, App Layer, GLOBAL. Added maintenance rules header. | GLOBAL | `QUERY_LOG.md`, `README.md`, `checkpoints/*.md` |
