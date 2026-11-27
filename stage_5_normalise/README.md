# Stage 5: Normalise

Token normalisation — taxonomy-based skill canonicalisation, output building, sealing, cache write.

## Responsibilities
- Load taxonomy from `config/taxonomy.yaml`
- Normalise tokens to canonical skills (exact match → rapidfuzz fuzzy ≥85)
- Build `Phase1Output` with sections, tokens, verdict, versions, timings, prev_hash
- Compute `report_hash` (stage5_root) excluding `timings_ms`
- Compute `signature` = Ed25519 sign of stage5_root + file_state_hash + versions
- Write output to DB cache via `cache_insert()`

## Key Functions
- `load_taxonomy()` — loads skills dict
- `normalise_tokens(tokens, taxonomy)` — deduplicate by canonical skill
- `build_output(...)` — builds Phase1Output with hash + signature
- `compute_report_hash(...)` — deterministic hash computation
- `write_cache(sha256, output)` — inserts into resume_cache

## Spec Coverage
See `checkpoints/stage5_normalise.md` for full spec gap analysis.
