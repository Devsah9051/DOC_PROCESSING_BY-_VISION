# README — Stage 2: Verify (Parse and Visual Verification)

Source specification: EGCA Phase 1 Final Specification rev4, Section 6 ("Stage 2: Parse and visual verification").

## Purpose

Stage 2 extracts words with positions, checks that each word is actually visible on the rendered page, rebuilds reading order from verified words only, and produces a clean, hashed artifact plus hidden-content findings. A PDF can contain text a person cannot see (white-on-white, tiny, hidden behind a picture); Stage 2 keeps only the words a person could actually see.

It works in two layers: a cheap detection layer (metadata and contrast check, ghost diff) and a heavy verification layer (OCR) that runs only on two triggers — scanned pages and anomalies.

## Steps

1. **Parse** — read the text layer: words, fonts, sizes, colours, positions, render modes. Links, annotations and metadata go to a separate side channel and are never mixed into the text.
2. **Render and split into frames** — each page rendered once at pinned render DPI, cut into frames from visible ink and white space (never from text positions).
3. **Detect** — two cheap checks (D0 metadata and contrast, D1 ghost diff) run on every word and frame. Anything not cleared is marked DOUBTFUL.
4. **Verify** — OCR runs only on the two triggers (scanned page, anomaly).
5. **Verdict per word or block** — CORROBORATED, CORROBORATED_FUZZY, UNCORROBORATED_NOT_VISIBLE, UNCORROBORATED_TEXT_MISMATCH, ICON_GLYPH, OCR_ONLY, TEXT_SOURCE.
6. **Rebuild reading order** — using verified words only (XY-cut on word positions), assign columns and order.
7. **Record and seal** — compute block hashes and `clean_artifact_sha256`. Write dropped words and OCR output to the forensic bundle. Record each hidden-content finding with severity.

## Detection layer (D0, D1)

| Check | What it does | Cost | Runs on |
|---|---|---|---|
| D0 Metadata and contrast | Invisible render mode, very small font, off-page position, text colour too close to background, text covered by shape/image, odd font mapping | Very low | Every word |
| D1 Ghost diff | Renders page with and without text layer; subtracts images. A word whose box does not change when text erased is not visible. Also finds visible ink no extracted word explains. | Low, once per page | Every frame |

## Colour contrast rule (6.4)

Measured by luminance contrast ratio `(L1 + 0.05) / (L2 + 0.05)` between relative luminance of lighter and darker of text colour and background behind the word. Background read from the render with text layer removed (the ghost-diff image). Threshold is a policy value (starting below ~1.5:1). Only unreadable low-contrast text is flagged; legible dark colours pass.

## Verdicts

| Verdict | Meaning | Used as claim? |
|---|---|---|
| CORROBORATED | In text layer and seen on render | Yes |
| CORROBORATED_FUZZY | Seen with small differences (ligatures, accents) | Yes |
| UNCORROBORATED_NOT_VISIBLE | In text layer, not visible | No; dropped and logged |
| UNCORROBORATED_TEXT_MISMATCH | Visible, reads differently from text layer | No; REVIEW |
| ICON_GLYPH | Symbol or icon font, not text | Ignored |
| OCR_ONLY | Read by OCR only (scanned page) | Yes, with parse-quality note |
| TEXT_SOURCE | Word from plain-text file; no rendering | Yes, marked not visually checked |

## OCR triggers (6.5)

- **Scanned page** — no embedded text layer or none usable; page read in full, words marked OCR_ONLY.
- **Anomaly** — detection layer mismatch; OCR reads only flagged boxes; whole page if widely affected.
- Confidence threshold (policy value); words below kept as `OCR_LOW_CONFIDENCE`, shown to reviewer, never used as claims.
- Budget: OCR work per file capped in pages and seconds; exceeding stops as PARTIAL and goes to REVIEW.
- English script only in v1; other scripts marked UNSUPPORTED_SCRIPT and file goes to REVIEW.

## OCR engine (6.6)

Default candidate: plain PaddleOCR text detection and recognition on CPU. Tesseract: baseline. PP-StructureV3: fallback only. Choice confirmed by comparison test (section 15) and pinned in run profile. Engine loaded once and held in memory.

## Hidden-content findings and parse status (6.8)

Findings with severity: words confirmed not visible, text layer/render disagreement, odd font map confirmed by OCR. Parse status: PARSED, PARSED_WITH_WARNINGS, PARTIAL, PARSE_FAILED.

## Injection scan (3.9 in code; spec 7.3)

Every file scanned for instruction-like text (hidden and visible, metadata, links, annotations). Strong patterns (e.g. "ignore all previous instructions") => critical flag leading to QUARANTINE. Weak patterns contribute to suspicion score.

## Functional Components

| Component | File | Responsibility |
|---|---|---|
| Text layer extractor | `stages/s2_verify/__init__.py` | Extracts spans with colour, size, opacity, font, render mode |
| Cheap rules (D0) | `stages/s2_verify/rules.py` | TINY_FONT, INVISIBLE_OPACITY, INVISIBLE_RENDER_MODE, OFF_PAGE, ZERO_WIDTH_CHAR, BIDI_CHAR, TAG_CHAR, MIXED_SCRIPT, PRIVATE_USE, GARBLED |
| Font rules | `stages/s2_verify/rules.py` | FONT_ANOMALY (Type3/custom), GARBLED with anomaly font |
| Renderer | `stages/s2_verify/render.py` | Renders page, builds text-erased copy for ghost diff |
| Ghost diff | `stages/s2_verify/render.py` | Compares original vs text-erased render to detect not-visible words |
| Contrast checker | `stages/s2_verify/render.py` | Luminance/WCAG contrast ratio against real background |
| OCR engine | `stages/s2_verify/ocr.py` | PaddleOCR CPU singleton; OCR on flagged regions |
| Injection scanner | `stages/s2_verify/rules.py` + `__init__.py` | Strong/weak pattern scan over visible text, metadata, links, annotations |
| Verdict computer | `stages/s2_verify/verdict.py` | QUARANTINED / SUSPICIOUS / CLEAN from weighted score |
| Classifier | `stages/s2_verify/verdict.py` | Matches text-layer words to OCR boxes (VERIFIED/MISMATCH/TEXT_ONLY/OCR_ONLY) |
| Clean text builder | `stages/s2_verify/verdict.py` | Reading-order clean text from verified + OCR_ONLY words |
| Audit sampler | `stages/s2_verify/__init__.py` | Deterministic audit sample keyed by SHA-256 |

## Implementation status

Completed:
- Text layer extraction with colour, size, opacity, font, render mode
- Cheap rules: TINY_FONT, INVISIBLE_OPACITY, INVISIBLE_RENDER_MODE, OFF_PAGE, ZERO_WIDTH_CHAR, BIDI_CHAR, TAG_CHAR, MIXED_SCRIPT, PRIVATE_USE, GARBLED
- Font rules: FONT_ANOMALY (Type3/custom), GARBLED with anomaly font
- Ghost diff (text erased vs original render comparison)
- Luminance contrast ratio check (WCAG)
- OCR region via PaddleOCR (CPU singleton)
- Injection scan (strong/weak patterns on visible text, metadata, links, annotations)
- Verdict computation: QUARANTINED (strong injection), SUSPICIOUS (weighted score >= threshold), CLEAN
- Clean text building with reading order (column detection)
- Matched (VERIFIED/MISMATCH/TEXT_ONLY) and OCR_ONLY classification
- Audit sample selection keyed by SHA-256

Stubbed / not yet wired:
- Frame cutting from rendered image (code cuts per-word regions, not frames)
- Full-page OCR for scans (partial: OCR on regions only)
- DOCX conversion and structure scan (spec 6.12)
- Plain-text TEXT route (spec 6.12)
- Forensic bundle write (forensic_ref)
- Page rotation/deskew, repeated headers/footers, watermarks, hyphen/letter-spaced repair (spec 6.11)

## Files

- `stages/s2_verify/__init__.py` — verify_pages orchestrator
- `stages/s2_verify/render.py` — render_page, make_text_erased, ghost_diff, contrast, wcag_ratio
- `stages/s2_verify/rules.py` — cheap_rules, font_rules, injection_scan
- `stages/s2_verify/verdict.py` — classify_text_layer, compute_verdict, build_clean_text
- `stages/s2_verify/ocr.py` — OcrBox, ocr_image, ocr_region

## Tests

`tests/test_s2_verify.py`: tiny font, zero-width, mixed script, garbled ratio, private use, injection strong/weak, font anomaly (Type3), ghost diff not-visible, contrast low, WCAG ratio, classify verified/OCR_ONLY/TEXT_ONLY, compute verdict strong injection/suspicious/clean.

`tests/test_pipeline.py`: injection (visible + metadata), tiny font, off-page, zero-width, white-on-white, covered text.
