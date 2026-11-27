# Stage 5: Normalise — Checkpoint Log

## Overview
**File:** `stages/s5_normalise.py`
**Pipeline Role:** Token normalisation — taxonomy-based skill canonicalisation, output building, report_hash computation, Ed25519 sealing, cache writing.
**Dependents:** `app/pipeline.py` Stage 5 block; `config/taxonomy.yaml`; `app/seal.py:seal_fields()`; `app/db.py:cache_insert()`.

---

## Purpose
- Load taxonomy from `config/taxonomy.yaml`
- Normalise tokens to canonical skills using exact match + rapidfuzz fuzzy matching (threshold 85)
- Build `Phase1Output` with sections, tokens, verdict, versions, timings, prev_hash
- Compute `report_hash` (stage5_root) = SHA-256 of canonical JSON (excluding report_hash, signature, timings_ms)
- Compute `signature` = Ed25519 sign of stage5_root + file_state_hash + versions
- Write output to DB cache via `cache_insert()`

---

## Current State

### Key Functions
- `load_taxonomy()` — loads `config/taxonomy.yaml` skills dict
- `_canonicalize(text, taxonomy)` — exact match → rapidfuzz fallback (>=85 threshold)
- `normalise_tokens(tokens, taxonomy)` — deduplicate by canonical skill, aggregate word_ids
- `build_output(...)` — builds `Phase1Output`, computes hash + signature
- `compute_report_hash(...)` — deterministic hash excluding timings_ms
- `write_cache(sha256, output)` — inserts into `resume_cache` table

---

## Applied Patches

| # | Change | Location | Reason |
|---|--------|----------|--------|
| 1 | Excluded `timings_ms` from report_hash | `build_output()` | Non-deterministic, broke hash stability |
| 2 | Added `compute_report_hash()` function | New | Decoupled hash computation from output building |
| 3 | Made `build_output` compute report_hash + signature | `build_output()` | Self-contained sealing |

---

## Configuration Dependencies (`config/config.yaml`)
| Key | Default | Used In Stage 5 |
|-----|---------|-----------------|
| `pipeline_version` | "1.0.0" | versions dict in output |
| `rules_version` | "1.0.0" | versions dict in output |

### `config/taxonomy.yaml`
10 skills with aliases and related terms: python, java, javascript, typescript, sql, aws, docker, kubernetes, machine_learning, project_management

---

## Test Coverage
**File:** `tests/test_s5_normalise.py`
| Test | Function | Status |
|------|----------|--------|
| `test_normalise_canonical_skills` | normalise_tokens() canonical + dedup | PASS |
| `test_normalise_unknown_skill_kept` | normalise_tokens() unknown skill passthrough | PASS |
| `test_build_output_hash_and_seal` | build_output() hash stability + signature | PASS |

---

## Known Issues & Remaining Tasks

| Issue | Severity | Details | Fix Needed |
|-------|----------|---------|------------|
| `timings_ms` excluded | FIXED | Was causing hash instability | RESOLVED |
| `write_cache` serializes full output | LOW | Cache stores signed output | Acceptable for Phase 1 |
| Fuzzy threshold hardcoded at 85 | MEDIUM | Uses literal 85, not config.fuzzy_threshold | Align with config.fuzzy_threshold |
| No confidence threshold filtering | LOW | Skills below 85 still included | Acceptable for Phase 1 |

### Spec Gaps (Section 9)
| Spec Ref | Requirement | Current State | Gap |
|----------|-------------|---------------|-----|
| 9.2 | Intake verifier: re-check record_root | NOT implemented | MISSING |
| 9.2 | Term normaliser: exact match, then alias match | Partial (exact + fuzzy) | MISSING negative pairs |
| 9.2 | Value normaliser: standard units | NOT implemented | MISSING |
| 9.2 | Provenance tags: STATED, NORMALIZED... | NOT implemented | MISSING |
| 9.2 | Status: PRESENT, UNMAPPED... | NOT implemented | MISSING |
| 9.3 | Skill relations | NOT implemented | MISSING |
| 9.4 | Invariants | NOT implemented | MISSING |
| 9.5 | Output: normalised record, relations, provenance | Partial | MISSING relation tags |
| 9.7 | Taxonomy source: ESCO/O*NET bases | Partial (hardcoded 10 skills) | MISSING proper taxonomy |

---

## Next Steps
1. Add provenance tags and status fields per Section 9.2
2. Implement skill relations per Section 9.3
3. Align fuzzy threshold with config.fuzzy_threshold
4. Expand taxonomy from public bases per Section 9.7

---

## Relevant File Links
- `stages/s5_normalise.py` — Stage 5 implementation
- `config/taxonomy.yaml` — skills taxonomy
- `app/seal.py` — seal_fields()
- `app/db.py` — cache_insert()
- `app/pipeline.py` — calls Stage 5 functions
- `tests/test_s5_normalise.py` — unit tests

---

## Checkpoint Status
**Status:** OPERATIONAL
**Last Verified:** 2026-11-27 — All 3 tests pass
**Next Review:** When fuzzy threshold alignment or provenance tags added
