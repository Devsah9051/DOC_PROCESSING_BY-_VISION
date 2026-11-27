# Stage 2: Verify — Checkpoint Log

## Overview
**Files:** `stages/s2_verify/__init__.py`, `stages/s2_verify/rules.py`, `stages/s2_verify/render.py`, `stages/s2_verify/ocr.py`, `stages/s2_verify/verdict.py`
**Pipeline Role:** Core verification — text-layer extraction, rule scanning, render/ghost-diff/contrast, OCR fallback, text/OCR matching, injection scanning, verdict computation.
**Dependents:** `app/pipeline.py:verify_pages()` call.

---

## Purpose
- Extract text-layer words with color, size, opacity, font, hidden-layer info
- Apply cheap rules (tiny font, opacity, render mode, off-page, zero-width, bidi, tag, mixed-script, private-use, garbled)
- Apply font rules (Type3/custom fonts → FONT_ANOMALY, garbled)
- Render page at configured DPI; create text-erased copy for ghost diff
- Compute ghost diff → NOT_VISIBLE detection
- Compute WCAG contrast → LOW_CONTRAST detection
- OCR gate: full page / audit sample / problem words / image regions
- Match text-layer words to OCR boxes by IoU + fuzzy threshold → VERIFIED/MISMATCH/TEXT_ONLY/OCR_ONLY
- Injection scan on text, metadata, links, annotations → INJECTION_STRONG / weak patterns
- Compute verdict: strong injection → QUARANTINE; weighted score → SUSPICIOUS; else CLEAN
- Build clean_text from VERIFIED + OCR_ONLY words in reading order

---

## Current State

### `stages/s2_verify/__init__.py` — `verify_pages()`
Returns block records, flags, matched words, OCR-only words, clean_text, verdict, parse status.

---

## Applied Patches (All Complete)

| # | File | Change | Reason |
|---|------|--------|--------|
| 1 | `stages/s2_verify/__init__.py` | Removed duplicate page-processing block | Block was doubled |
| 2 | `stages/s2_verify/__init__.py` | Changed render condition from `has_text_layer` to `words` | Ghost diff/contrast must run on any page with text |
| 3 | `stages/s2_verify/__init__.py` | Fixed OCR loop: `full_images[pno]` instead of `page_images[pno][0]` | None for pages without text layer |
| 4 | `stages/s2_verify/render.py` | `add_redact_rect` → `add_redact_annot` | PyMuPDF API |
| 5 | `stages/s2_verify/render.py` | `_int_color` handles list/tuple color values | PyMuPDF span color can be list |
| 6 | `stages/s2_verify/rules.py` | `int(word.get("flags", 0))` guarded against list type | `int()` on list raises TypeError |
| 7 | `stages/s2_verify/verdict.py` | Case-insensitive weight lookup | Config keys lowercase, rule IDs UPPER_SNAKE |
| 8 | `stages/s2_verify/rules.py` | Added COVERED_BY_SHAPE rule | Text covered by white rect |
| 9 | `stages/s2_verify/rules.py` | Added `\u00b7` to ZERO_WIDTH chars | PyMuPDF converts `\u200b` to `\u00b7` |

---

## Configuration Dependencies (`config/config.yaml`)
| Key | Default | Used In |
|-----|---------|---------|
| `dpi` | 150 | render_page, make_text_erased |
| `contrast_min` | 1.5 | contrast low_contrast threshold |
| `min_ink` | 0.02 | ghost_diff not_visible threshold |
| `ghost_diff_threshold` | 40 | ghost_diff diff threshold |
| `ocr_margin` | 4 | crop margin around word bbox |
| `iou_threshold` | 0.30 | classify_text_layer IoU match |
| `fuzzy_threshold` | 85 | classify_text_layer fuzzy match |
| `tiny_font_max_pt` | 6.0 | cheap_rules TINY_FONT |
| `suspicious_score` | 5.0 | compute_verdict status threshold |
| `weights` | various | compute_verdict per-rule weights |
| `audit_rate` | 0.05 | audit_sample deterministic page sampling |

---

## Test Coverage
**File:** `tests/test_s2_verify.py`
| Test | Function | Status |
|------|----------|--------|
| `test_tiny_font_flagged` | cheap_rules TINY_FONT | PASS |
| `test_zero_width_flagged` | has_zero_width | PASS |
| `test_mixed_script` | mixed_script | PASS |
| `test_garbled_ratio` | garbled_ratio | PASS |
| `test_private_use` | has_private_use | PASS |
| `test_injection_strong` | injection_scan strong | PASS |
| `test_injection_weak` | injection_scan weak | PASS |
| `test_font_anomaly_type3` | font_rules FONT_ANOMALY | PASS |
| `test_ghost_diff_not_visible` | ghost_diff identical images | PASS |
| `test_contrast_low` | contrast white-on-white | PASS |
| `test_wcag_ratio` | wcag_ratio black-on-white | PASS |
| `test_classify_verified` | classify_text_layer VERIFIED | PASS |
| `test_classify_ocr_only` | classify_text_layer OCR_ONLY | PASS |
| `test_classify_text_only` | classify_text_layer TEXT_ONLY | PASS |
| `test_compute_verdict_strong_injection` | compute_verdict QUARANTINE | PASS |
| `test_compute_verdict_clean` | compute_verdict REVIEW | PASS |
| `test_compute_verdict_suspicious` | compute_verdict QUARANTINE | PASS |

**File:** `tests/test_pipeline.py` (integration via Stage 2)
- Multiple integration tests pass

---

## Known Issues & Remaining Tasks

| Issue | Severity | Details | Fix Needed |
|-------|----------|---------|------------|
| PaddleOCR model download | HIGH | First OCR run downloads models; may be slow offline | Pre-download models |
| Off-page text clipped | MEDIUM | PyMuPDF returns empty for text outside page rect | Test fixture needs in-page bbox |
| Zero-width char conversion | MEDIUM | PyMuPDF converts `\u200b` to `\u00b7` | Added `\u00b7` to ZERO_WIDTH set |
| Covered text ghost diff | MEDIUM | White rect may leave ink > threshold | Added COVERED_BY_SHAPE rule |
| Duplicate processing block | FIXED | Was doubling all flags per page | RESOLVED |
| `has_text_layer` → `words` | FIXED | Ghost diff/contrast now runs on any page with words | RESOLVED |
| OCR `orig=None` crash | FIXED | `full_images[pno]` used instead of `page_images[pno][0]` | RESOLVED |

---

## Next Steps
1. Pre-download PaddleOCR models
2. Tune `min_ink` and `ghost_diff_threshold` on real documents
3. Add OCR confidence threshold filtering
4. Implement frame splitting per Section 6.2

---

## Relevant File Links
- `stages/s2_verify/__init__.py` — verify_pages() main entry
- `stages/s2_verify/rules.py` — cheap_rules, font_rules, injection_scan
- `stages/s2_verify/render.py` — render_page, make_text_erased, ghost_diff, contrast
- `stages/s2_verify/ocr.py` — ocr_region, ocr_image
- `stages/s2_verify/verdict.py` — classify_text_layer, compute_verdict
- `config/config.yaml` — Stage 2 config keys
- `tests/test_s2_verify.py` — unit tests
- `tests/test_pipeline.py` — integration tests

---

## Checkpoint Status
**Status:** OPERATIONAL (with environment-related test caveats)
**Last Verified:** 2026-11-27 — All unit tests pass; 41/41 total tests pass
**Next Review:** When PaddleOCR models are pre-downloaded or thresholds retuned
