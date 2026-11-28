from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from rapidfuzz import fuzz

from app.config import config
from stages.s2_verify.rules import scan_document_texts
from stages.s2_verify.ocr import OcrBox

VERIFIED = "CORROBORATED"
OCR_ONLY = "OCR_ONLY"
MISMATCH = "UNCORROBORATED_TEXT_MISMATCH"
TEXT_ONLY = "TEXT_SOURCE"
NOT_VISIBLE = "UNCORROBORATED_NOT_VISIBLE"
ICON_GLYPH = "ICON_GLYPH"


def _iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


def _fuzzy(t1: str, t2: str) -> float:
    if not t1 or not t2:
        return 0.0
    return fuzz.ratio(t1, t2)


@dataclass
class MatchedWord:
    word_id: str
    page: int
    bbox: Tuple[float, float, float, float]
    text: str
    source: str
    visible: bool
    flags: List[str]
    classification: str  # VERIFIED | OCR_ONLY | MISMATCH | TEXT_ONLY | None (ocr-only words)
    # Optional typography data (Stage 4 support — additive, defaults None)
    size: Optional[float] = None
    bold: Optional[bool] = None
    color: Optional[int] = None
    font: Optional[str] = None


def classify_text_layer(
    text_words: List[dict],
    ocr_boxes: List[OcrBox],
    iou_threshold: float = None,
    fuzzy_threshold: int = None,
) -> Tuple[List[MatchedWord], List[OcrBox]]:
    """3.8 Match text-layer words to OCR boxes by IoU + fuzzy.
    Returns (matched text-layer words, unmatched OCR boxes => OCR_ONLY)."""
    if iou_threshold is None:
        iou_threshold = config.iou_threshold
    if fuzzy_threshold is None:
        fuzzy_threshold = config.fuzzy_threshold

    matched: List[MatchedWord] = []
    used_ocr = set()

    for w in text_words:
        bbox = tuple(w["bbox"])  # page pts
        text = w.get("text", "")
        visible = w.get("visible", True)
        flags = list(w.get("flags", []))
        wid = w.get("word_id", "")
        page = w.get("page", 0)
        source = w.get("source", "text_layer")

        best = None
        best_iou = 0.0
        for idx, ob in enumerate(ocr_boxes):
            obbox = tuple(ob.bbox)
            iou = _iou(bbox, obbox)
            if iou >= iou_threshold and iou > best_iou:
                best_iou = iou
                best = (idx, ob.text)

        if best is None:
            if visible:
                # visible in text layer but OCR did not find it
                flags.append(TEXT_ONLY)
                classification = TEXT_ONLY
            else:
                classification = None  # hidden text, already flagged; do not emit as token
            matched.append(
                MatchedWord(
                    wid, page, bbox, text, source, visible, flags, classification,
                    size=w.get("size"),
                    bold=w.get("bold"),
                    color=w.get("color"),
                    font=w.get("font"),
                )
            )
            continue

        idx, obtext = best
        used_ocr.add(idx)
        sim = _fuzzy(text, obtext)
        if sim >= fuzzy_threshold:
            classification = VERIFIED
        else:
            classification = MISMATCH
            flags.append(MISMATCH)
        matched.append(
            MatchedWord(
                wid, page, bbox, text, source, visible, flags, classification,
                size=w.get("size"),
                bold=w.get("bold"),
                color=w.get("color"),
                font=w.get("font"),
            )
        )

    unmatched = [ocr_boxes[i] for i in range(len(ocr_boxes)) if i not in used_ocr]
    return matched, unmatched


def compute_verdict(
    flags: List[tuple],
    strong_injection: bool,
    weak_score: float,
    weights: dict,
) -> object:
    """3.10 Verdict: strong injection => QUARANTINED. Weighted score > threshold => SUSPICIOUS.
    flags: list of (rule_id, evidence, severity)."""
    from app.schemas import Verdict

    score = 0.0
    rules = []
    reasons = []
    weight_lut = {k.lower(): v for k, v in weights.items()}
    for rule_id, evidence, severity in flags:
        w = float(weight_lut.get(rule_id.lower(), 1.0))
        score += w
        rules.append(rule_id)
        reasons.append(f"{rule_id}: {evidence}")

    if strong_injection:
        status = "QUARANTINE"
        reasons.insert(0, "INJECTION_STRONG: strong injection pattern detected")
    elif score >= config.quarantine_threshold:
        status = "QUARANTINE"
        reasons.insert(0, f"weighted_score={score:.2f} >= quarantine_threshold={config.quarantine_threshold}")
    elif score >= config.review_threshold:
        status = "REVIEW"
        reasons.insert(0, f"weighted_score={score:.2f} >= review_threshold={config.review_threshold}")
    else:
        status = "CLEAN"

    return Verdict(status=status, score=round(score, 2), rules=rules, reasons=reasons)


def build_clean_text(matched: List[MatchedWord], ocr_only: List[OcrBox]) -> str:
    """3.11 clean_text = VERIFIED + OCR_ONLY words in reading order.
    Sort blocks, split columns by x-gap."""
    words = []
    for w in matched:
        if w.classification == VERIFIED and w.visible:
            words.append(w)
    for ob in ocr_only:
        words.append(
            MatchedWord(
                word_id=f"ocr-{ob.page}-{round(ob.bbox[0])}-{round(ob.bbox[1])}",
                page=ob.page,
                bbox=tuple(ob.bbox),
                text=ob.text,
                source="ocr",
                visible=True,
                flags=[],
                classification=OCR_ONLY,
            )
        )
    if not words:
        return ""
    return _reading_order_text(words)


def _reading_order_text(words: List[MatchedWord]) -> str:
    """3.11 clean_text = VERIFIED + OCR_ONLY words in reading order.
    Preserve line breaks: emit "\\n" between lines (group by page+y).
    Sort words left-to-right within each line."""
    if not words:
        return ""

    # Group words into lines by (page, y rounded to line tolerance ~10pt)
    lines: dict[tuple[int, int], list[str]] = {}
    line_order: list[tuple[int, int]] = []

    for w in words:
        if not w.text.strip():
            continue
        key = (w.page, round(w.bbox[1] / 10) * 10)  # Round y to nearest 10pt = line bucket
        if key not in lines:
            lines[key] = []
            line_order.append(key)
        lines[key].append(w)

    # Sort line keys by (page, y)
    line_order.sort()

    # Within each line, sort words by x (left-to-right)
    output_lines = []
    for key in line_order:
        line_words = sorted(lines[key], key=lambda w: round(w.bbox[0]))
        output_lines.append(" ".join(w.text for w in line_words if w.text.strip()))

    return "\n".join(output_lines)


def _sort_column(words):
    return sorted(words, key=lambda w: (round(w.bbox[1]) / 10, round(w.bbox[0])))
