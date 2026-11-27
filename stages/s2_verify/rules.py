from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List

import pymupdf

from app.config import config

ZERO_WIDTH = "\u200b\u200c\u200d\ufeff\u00b7"
BIDI_MARKS = "\u200e\u200f"
TAG_START = 0xE0000
TAG_END = 0xE0FFF
PRIVATE_USE_RANGES = [(0xE000, 0xF8FF), (0xF0000, 0xFFFFD), (0x100000, 0x10FFFD)]


def _has_chars(text: str, chars: str) -> bool:
    return any(c in chars for c in text)


def _has_zero_width(text: str) -> bool:
    return _has_chars(text, ZERO_WIDTH)


def _has_bidi(text: str) -> bool:
    return _has_chars(text, BIDI_MARKS)


def _has_tag(text: str) -> bool:
    return any(TAG_START <= ord(c) <= TAG_END for c in text)


def _is_private_use(c: str) -> bool:
    o = ord(c)
    return any(lo <= o <= hi for lo, hi in PRIVATE_USE_RANGES)


def _has_private_use(text: str) -> bool:
    return any(_is_private_use(c) for c in text)


def _script_of(c: str) -> str:
    o = ord(c)
    if 0x0020 <= o <= 0x007F:
        return "latin"
    if 0x00C0 <= o <= 0x024F:
        return "latin_ext"
    if 0x0370 <= o <= 0x03FF:
        return "greek"
    if 0x0400 <= o <= 0x04FF:
        return "cyrillic"
    if 0x0590 <= o <= 0x05FF:
        return "hebrew"
    if 0x0600 <= o <= 0x06FF:
        return "arabic"
    if 0x4E00 <= o <= 0x9FFF:
        return "cjk"
    if 0x3040 <= o <= 0x30FF:
        return "kana"
    if 0x30A0 <= o <= 0x30FF:
        return "kana"
    if 0xAC00 <= o <= 0xD7AF:
        return "hangul"
    if 0x0900 <= o <= 0x097F:
        return "devanagari"
    if 0x0E00 <= o <= 0x0E7F:
        return "thai"
    return "other"


def _mixed_script(text: str) -> bool:
    scripts = {_script_of(c) for c in text if c.isalnum()}
    scripts.discard("other")
    return len(scripts) > 1


def _garbled_ratio(text: str) -> float:
    if not text:
        return 0.0
    bad = sum(
        1
        for c in text
        if ord(c) == 0xFFFD
        or ord(c) < 0x20 and c not in "\t\n\r"
        or _is_private_use(c)
    )
    return bad / len(text)


@dataclass
class RuleFlag:
    rule_id: str
    evidence: str
    severity: str


def cheap_rules(word: dict, page_rect: pymupdf.Rect, page) -> List[RuleFlag]:
    """3.2 Cheap rules, no render. word = span/word dict with bbox,text,size,color,flags,font."""
    flags: List[RuleFlag] = []
    text = word.get("text", "")
    size = float(word.get("size", 0) or 0)
    bbox = pymupdf.Rect(word.get("bbox", [0, 0, 0, 0]))

    # tiny font
    if size and size < config.tiny_font_max_pt and text.strip():
        flags.append(RuleFlag("TINY_FONT", f"font_size={size:.1f}pt", "medium"))

    # opacity ~ 0
    alpha = word.get("alpha")
    if alpha is not None and float(alpha) < 0.02 and text.strip():
        flags.append(RuleFlag("INVISIBLE_OPACITY", f"alpha={float(alpha):.2f}", "high"))

    # invisible render mode (text rendering mode 3 = invisible)
    rend = word.get("render_mode")
    if rend is None:
        flags_val = word.get("flags", 0)
        rend = _render_mode_from_flags(int(flags_val) if not isinstance(flags_val, (list, tuple)) else 0)
    if rend == 3 and text.strip():
        flags.append(RuleFlag("INVISIBLE_RENDER_MODE", "render_mode=invisible", "high"))

    # off-page bbox
    if not page_rect.contains(bbox):
        flags.append(RuleFlag("OFF_PAGE", f"bbox={bbox}", "medium"))

    # covered by drawn shape (white rect over text, etc.)
    try:
        drawings = page.get_drawings() or []
        for drawing in drawings:
            d_rect = drawing.get("rect")
            if d_rect:
                inter = d_rect & bbox
                if not inter.is_empty:
                    fill = drawing.get("fill")
                    if fill is not None:
                        flags.append(RuleFlag("COVERED_BY_SHAPE", f"covered by fill={fill}", "medium"))
                        break
    except Exception:
        pass

    # zero-width / bidi / tag chars
    if _has_zero_width(text):
        flags.append(RuleFlag("ZERO_WIDTH_CHAR", "zero-width/format char", "medium"))
    if _has_bidi(text):
        flags.append(RuleFlag("BIDI_CHAR", "bidi mark", "low"))
    if _has_tag(text):
        flags.append(RuleFlag("TAG_CHAR", "tag character", "medium"))

    # mixed-script words
    if _mixed_script(text):
        flags.append(RuleFlag("MIXED_SCRIPT", f"scripts in '{text[:20]}'", "low"))

    # private-use / icon-font chars
    if _has_private_use(text):
        flags.append(RuleFlag("PRIVATE_USE", "private-use/icon-font char", "medium"))

    # garbled text ratio
    gr = _garbled_ratio(text)
    if gr > 0.30 and text.strip():
        flags.append(RuleFlag("GARBLED", f"garbled_ratio={gr:.2f}", "medium"))

    return flags


def font_rules(word: dict) -> List[RuleFlag]:
    """3.3 Font maps: Type3 / custom encodings that also give garbled text."""
    flags: List[RuleFlag] = []
    text = word.get("text", "")
    font = str(word.get("font", "") or "")
    font_lower = font.lower()
    is_anomaly = "type3" in font_lower or "custom" in font_lower or "#" in font
    if is_anomaly and text.strip():
        flags.append(RuleFlag("FONT_ANOMALY", f"font={font}", "medium"))
        if _garbled_ratio(text) > 0.20:
            flags.append(RuleFlag("GARBLED", "garbled with anomaly font", "medium"))
    return flags


def _render_mode_from_flags(flags_int: int) -> int | None:
    # Best-effort: PyMuPDF span flags do not directly expose PDF text render mode.
    # Return None unless a dedicated render_mode field is present.
    return None


# ---- 3.9 injection scan ----

_STRONG = [re.compile(p, re.I) for p in config.injection.get("strong", [])]
_WEAK = [re.compile(p, re.I) for p in config.injection.get("weak", [])]


def injection_scan(text: str) -> tuple[bool, float]:
    """Return (strong_hit, weak_score). strong => hard quarantine flag."""
    strong = any(rx.search(text) for rx in _STRONG)
    weak_score = sum(1.0 for rx in _WEAK if rx.search(text))
    return strong, weak_score


def scan_document_texts(texts: Iterable[str]) -> tuple[bool, float]:
    strong = False
    weak = 0.0
    for t in texts:
        s, w = injection_scan(t)
        strong = strong or s
        weak += w
    return strong, weak
