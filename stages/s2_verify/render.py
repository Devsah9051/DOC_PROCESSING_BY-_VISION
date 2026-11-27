from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import cv2
import numpy as np
import pymupdf

from app.config import config

PDF_REDACT_IMAGE_NONE = getattr(pymupdf, "PDF_REDACT_IMAGE_NONE", 0)
PDF_REDACT_GRAPHICS_NONE = getattr(pymupdf, "PDF_REDACT_GRAPHICS_NONE", 0)


def _pixmap_to_array(pix) -> np.ndarray:
    n = pix.n
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, n).copy()
    if n == 4:
        arr = arr[:, :, :3].copy()
    elif n == 1:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2RGB)
    return arr


def render_page(page: pymupdf.Page, dpi: int) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi)
    return _pixmap_to_array(pix)


@dataclass
class ErasedResult:
    image: np.ndarray
    doc: object


def make_text_erased(doc: pymupdf.Document, page_num: int, dpi: int) -> ErasedResult:
    """3.4 Render a copy of the page with the text layer erased (white fill),
    keeping images and graphics. Raises if erasure fails."""
    doc2 = pymupdf.open()
    doc2.insert_pdf(doc, from_page=page_num, to_page=page_num)
    page = doc2[0]
    d = page.get_text("dict")
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text.strip():
                    continue
                r = pymupdf.Rect(span["bbox"])
                page.add_redact_annot(r, fill=(1, 1, 1))
    page.apply_redactions(
        images=PDF_REDACT_IMAGE_NONE,
        graphics=PDF_REDACT_GRAPHICS_NONE,
    )
    pix = page.get_pixmap(dpi=dpi)
    image = _pixmap_to_array(pix)
    doc2.close()
    return ErasedResult(image=image, doc=None)


@dataclass
class GhostDiffResult:
    ink: float
    not_visible: bool


def ghost_diff(orig: np.ndarray, erased: np.ndarray, threshold: int = None) -> GhostDiffResult:
    """3.5 Ink share of pixels differing between original and erased crop."""
    if threshold is None:
        threshold = config.ghost_diff_threshold
    if orig.shape != erased.shape:
        erased = cv2.resize(erased, (orig.shape[1], orig.shape[0]))
    g_orig = cv2.cvtColor(orig, cv2.COLOR_RGB2GRAY)
    g_era = cv2.cvtColor(erased, cv2.COLOR_RGB2GRAY)
    diff = cv2.absdiff(g_orig, g_era)
    ink = float((diff > threshold).mean())
    return GhostDiffResult(ink=ink, not_visible=ink < config.min_ink)


def _relative_luminance(rgb: Tuple[int, int, int]) -> float:
    r, g, b = [c / 255.0 for c in rgb]
    lin = []
    for c in (r, g, b):
        lin.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def wcag_ratio(color1, color2) -> float:
    l1 = _relative_luminance(color1)
    l2 = _relative_luminance(color2)
    light = max(l1, l2)
    dark = min(l1, l2)
    return (light + 0.05) / (dark + 0.05)


def _int_color(int_color) -> Tuple[int, int, int]:
    if isinstance(int_color, (list, tuple)):
        value = (int(int_color[0]) << 16) | (int(int_color[1]) << 8) | int(int_color[2])
    else:
        value = int(int_color) & 0xFFFFFF
    return (value >> 16, (value >> 8) & 0xFF, value & 0xFF)


@dataclass
class ContrastResult:
    ratio: float
    low_contrast: bool


def contrast(text_color_int, erased_crop: np.ndarray) -> ContrastResult:
    """3.6 Contrast: text colour vs median colour of erased crop (true background)."""
    text_rgb = _int_color(text_color_int)
    med = np.median(erased_crop.reshape(-1, 3), axis=0)
    bg_rgb = (int(med[0]), int(med[1]), int(med[2]))
    ratio = wcag_ratio(text_rgb, bg_rgb)
    return ContrastResult(ratio=ratio, low_contrast=ratio < config.contrast_min)
