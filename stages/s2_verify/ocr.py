from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np
import pymupdf
from rapidfuzz import fuzz

from app.config import config
from app.db import pool  # noqa: F401  (ensures db importable; pool used by app)

@dataclass
class OcrBox:
    page: int
    bbox: List[float]  # page coords [x0,y0,x1,y1]
    text: str
    confidence: float


_ocr_singleton = None


def _get_ocr():
    global _ocr_singleton
    if _ocr_singleton is None:
        from paddleocr import PaddleOCR
        _ocr_singleton = PaddleOCR(use_doc_ocr=False, use_doc_v2=False, lang="en", show_log=False)
    return _ocr_singleton


def _scale() -> float:
    return config.dpi / 72.0


def _points_to_pixels(bbox_pts, scale):
    return [round(c * scale) for c in bbox_pts]


def _pixels_to_points(pixels, scale):
    return [p / scale for p in pixels]


def _parse_ocr_result(res) -> List[tuple]:
    """Return list of (bbox_px [x0,y0,x1,y1], text, conf) from a PaddleOCR result."""
    out = []
    try:
        boxes = res.boxes
        texts = res.texts
        scores = res.scores
    except Exception:
        return out
    if boxes is None:
        return out
    try:
        boxes = boxes.cpu().numpy() if hasattr(boxes, "cpu") else np.asarray(boxes)
    except Exception:
        boxes = np.asarray(boxes)
    texts = texts or []
    scores = scores or []
    n = min(len(boxes), len(texts), len(scores))
    for i in range(n):
        box = boxes[i]
        try:
            pts = np.asarray(box).reshape(-1, 2)
        except Exception:
            continue
        x0, y0 = float(pts[:, 0].min()), float(pts[:, 1].min())
        x1, y1 = float(pts[:, 0].max()), float(pts[:, 1].max())
        text = str(texts[i]) if i < len(texts) else ""
        conf = float(scores[i]) if i < len(scores) else 0.0
        out.append(([x0, y0, x1, y1], text, conf))
    return out


def ocr_image(image_rgb: np.ndarray) -> List[tuple]:
    """Run PaddleOCR on an RGB image. Returns list of (bbox_px, text, conf)."""
    try:
        ocr = _get_ocr()
        res = ocr.predict(image_rgb)
    except Exception:
        return []
    boxes: List[tuple] = []
    if not res:
        return boxes
    for r in res:
        boxes.extend(_parse_ocr_result(r))
    return boxes


def ocr_region(image_rgb: np.ndarray, region_pts: List[float], page: int) -> List[OcrBox]:
    """OCR a rectangular region (page pts). Map boxes back to page coords."""
    scale = _scale()
    x0, y0, x1, y1 = [c / scale for c in region_pts]
    x0i, y0i, x1i, y1i = [int(round(c)) for c in (x0, y0, x1, y1)]
    crop = image_rgb[max(y0i, 0):max(y1i, 0), max(x0i, 0):max(x1i, 0)]
    if crop.size == 0:
        return []
    out: List[OcrBox] = []
    for (bx0, by0, bx1, by1), text, conf in ocr_image(crop):
        px = [bx0 / scale + x0, by0 / scale + y0, bx1 / scale + x0, by1 / scale + y0]
        out.append(OcrBox(page=page, bbox=[round(v, 2) for v in px], text=text, confidence=round(conf, 3)))
    return out
