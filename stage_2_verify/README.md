# Stage 2: Verify

Core verification layer — text extraction, rule scanning, render/ghost-diff/contrast, OCR fallback, verdict computation.

## Responsibilities
- Extract text-layer words with color, size, opacity, font
- Apply cheap rules (tiny font, opacity, render mode, off-page, zero-width)
- Apply font rules (Type3/custom fonts)
- Render page at configured DPI; create text-erased copy
- Ghost diff detection (NOT_VISIBLE)
- Contrast detection (LOW_CONTRAST)
- OCR gate for scanned pages and anomalies
- Match text-layer words to OCR boxes
- Injection scan
- Compute verdict: CLEAN / REVIEW / QUARANTINE

## Submodules
- `__init__.py` — `verify_pages()` main entry
- `rules.py` — cheap rules, font rules, injection scan
- `render.py` — page rendering, ghost diff, contrast
- `ocr.py` — OCR engine
- `verdict.py` — verdict computation

## Spec Coverage
See `checkpoints/stage2_verify.md` for full spec gap analysis.
