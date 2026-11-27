from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Tuple

SECTION_ALIASES = [
    "summary", "professional summary", "objective",
    "experience", "work experience", "employment", "professional experience",
    "education", "skills", "technical skills", "certifications",
    "projects", "publications", "contact", "personal details",
]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|[A-Za-z]+\s+\d{4})\b")
MONTH_YEAR_RE = re.compile(r"\b([A-Za-z]+)\s+(\d{4})\b")


@dataclass
class Field:
    name: str
    value: str
    word_ids: List[str] = field(default_factory=list)
    bbox: List[float] = field(default_factory=list)


@dataclass
class Section:
    name: str
    text: str
    word_ids: List[str] = field(default_factory=list)
    bbox: List[float] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0


def _find_word_id(word_records, needle: str, used: set) -> Tuple[Optional[str], List[float]]:
    needle_l = needle.strip().lower()
    if not needle_l:
        return None, []
    for wr in word_records:
        if wr.word_id in used:
            continue
        wr_text = wr.text.strip().lower()
        if needle_l == wr_text or needle_l in wr_text or wr_text in needle_l:
            used.add(wr.word_id)
            return wr.word_id, list(wr.bbox)
    return None, []


def extract_structure(clean_text: str, word_records) -> Tuple[List[Section], List[Field]]:
    """5.1 Sections from alias list. 5.2 Fields by regex with word_ids."""
    lines = [ln.strip() for ln in clean_text.splitlines() if ln.strip()]
    sections: List[Section] = []
    current: Optional[Section] = None

    for idx, ln in enumerate(lines):
        ln_l = ln.lower()
        alias = None
        for a in SECTION_ALIASES:
            if ln_l == a or ln_l.startswith(a + " ") or ln_l.startswith(a + ":"):
                alias = a
                break
        if alias:
            if current:
                sections.append(current)
            current = Section(name=alias, text=ln, start_line=idx, end_line=idx)
            wid, bbox = _find_word_id(word_records, ln, set())
            if wid:
                current.word_ids.append(wid)
                current.bbox = bbox
        else:
            if current is not None:
                current.text += " " + ln
                current.end_line = idx
                wid, _ = _find_word_id(word_records, ln, set())
                if wid:
                    current.word_ids.append(wid)
    if current:
        sections.append(current)

    # 5.2 Fields
    fields: List[Field] = []
    used_word_ids: set = set()
    for m in EMAIL_RE.finditer(clean_text):
        wid, bbox = _find_word_id(word_records, m.group(0), used_word_ids)
        fields.append(Field(name="email", value=m.group(0), word_ids=[wid] if wid else [], bbox=bbox))
    for m in PHONE_RE.finditer(clean_text):
        wid, bbox = _find_word_id(word_records, m.group(0), used_word_ids)
        fields.append(Field(name="phone", value=m.group(0), word_ids=[wid] if wid else [], bbox=bbox))
    for m in DATE_RE.finditer(clean_text):
        wid, bbox = _find_word_id(word_records, m.group(0), used_word_ids)
        fields.append(Field(name="date", value=m.group(0), word_ids=[wid] if wid else [], bbox=bbox))

    # consistency checks
    _check_dates(fields)
    return sections, fields


def _check_dates(fields: List[Field]):
    today = date.today()
    parsed = []
    for f in fields:
        if f.name != "date":
            continue
        d = _parse_date(f.value)
        if d:
            parsed.append((f, d))
    for f, d in parsed:
        if d > today:
            f.name = "date:future"
    # end-before-start / overlap heuristics on consecutive date fields
    parsed_sorted = sorted(parsed, key=lambda x: x[1])
    for i in range(1, len(parsed_sorted)):
        if parsed_sorted[i][1] < parsed_sorted[i - 1][1]:
            parsed_sorted[i][0].name = "date:end_before_start"


def _parse_date(value: str) -> Optional[date]:
    m = MONTH_YEAR_RE.search(value)
    if m:
        try:
            return datetime.strptime(m.group(0), "%B %Y").date()
        except Exception:
            try:
                return datetime.strptime(m.group(0), "%b %Y").date()
            except Exception:
                return None
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except Exception:
            continue
    return None
