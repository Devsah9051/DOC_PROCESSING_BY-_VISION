from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Tuple, Dict, Set

from app.config import config
from app.hash import record_hash
from app.schemas import WordRecord, Section as SchemaSection, Field as SchemaField

# ---------------------------------------------------------------------------
# Section aliases (canonical name -> list of display aliases)
# ---------------------------------------------------------------------------
SECTION_ALIASES: Dict[str, List[str]] = {
    "contact": ["contact", "personal details", "personal information"],
    "summary": ["summary", "professional summary", "profile", "objective", "career objective"],
    "experience": ["experience", "work experience", "employment", "professional experience", "work history"],
    "education": ["education", "academic background", "qualifications"],
    "skills": ["skills", "technical skills", "core competencies", "expertise"],
    "certifications": ["certifications", "certificates", "licenses"],
    "projects": ["projects", "key projects", "selected projects"],
    "publications": ["publications", "research publications", "papers"],
    "awards": ["awards", "honors", "achievements"],
    "references": ["references", "professional references"],
}

# Reverse lookup: display alias -> canonical section name
_ALIAS_TO_CANONICAL: Dict[str, str] = {}
for canon, aliases in SECTION_ALIASES.items():
    _ALIAS_TO_CANONICAL[canon] = canon
    for a in aliases:
        _ALIAS_TO_CANONICAL[a.lower()] = canon

# ---------------------------------------------------------------------------
# Regex patterns (compiled once at module level)
# ---------------------------------------------------------------------------
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|[A-Za-z]+\s+\d{4})\b")
MONTH_YEAR_RE = re.compile(r"\b([A-Za-z]+)\s+(\d{4})\b")
URL_RE = re.compile(r"https?://[^\s<>\"]+|www\.[^\s<>\"]+")
LINKEDIN_RE = re.compile(r"linkedin\.com/in/[^\s<>\"]+", re.IGNORECASE)
GITHUB_RE = re.compile(r"github\.com/[^\s<>\"]+", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Rule families (Section 8.4)
# ---------------------------------------------------------------------------
# R1-R11: Resume structure / integrity rules
RULE_R1 = "R1_MISSING_REQUIRED_SECTION"
RULE_R2 = "R2_DUPLICATE_SECTION"
RULE_R3 = "R3_EMPTY_SECTION"
RULE_R4 = "R4_OUT_OF_ORDER_SECTIONS"
RULE_R5 = "R5_UNKNOWN_SECTION"
RULE_R6 = "R6_INVALID_EMAIL_FORMAT"
RULE_R7 = "R7_INVALID_PHONE_FORMAT"
RULE_R8 = "R8_DATE_IN_FUTURE"
RULE_R9 = "R9_END_BEFORE_START"
RULE_R10 = "R10_GAP_IN_EMPLOYMENT"
RULE_R11 = "R11_INCONSISTENT_DATE_FORMAT"

# F1-F6: Formatting / presentation rules
RULE_F1 = "F1_MIXED_DATE_FORMATS"
RULE_F2 = "F2_INCONSISTENT_FONT_SIZES"
RULE_F3 = "F3_OVERLAPPING_TEXT_BLOCKS"
RULE_F4 = "F4_TEXT_OUTSIDE_MARGINS"
RULE_F5 = "F5_UNUSUAL_CHARACTER_SPACING"
RULE_F6 = "F6_WATERMARK_OR_BACKGROUND"

# J1-J3: Job description track rules
RULE_J1 = "J1_MISSING_REQUIREMENTS_SECTION"
RULE_J2 = "J2_MISSING_RESPONSIBILITIES"
RULE_J3 = "J3_VAGUE_QUALIFICATIONS"

# ---------------------------------------------------------------------------
# Manipulation flags M1-M5 (Section 8.5)
# ---------------------------------------------------------------------------
FLAG_M1 = "M1_HIDDEN_TEXT"
FLAG_M2 = "M2_REMAPPED_GLYPH"
FLAG_M3 = "M3_OVERLAPPING_BBOX"
FLAG_M4 = "M4_TEXT_OUTSIDE_VISIBLE"
FLAG_M5 = "M5_ANOMALOUS_FONT_MAP"

# ---------------------------------------------------------------------------
# Labels (Section 8.4)
# ---------------------------------------------------------------------------
LABEL_CONTRADICTION = "CONTRADICTION"
LABEL_CONFLICT = "CONFLICT"
LABEL_FACT = "FACT"
LABEL_NOT_EVALUATED = "NOT_EVALUATED"

# ---------------------------------------------------------------------------
# WordIndex: O(1) text→word_id lookup with spatial awareness
# ---------------------------------------------------------------------------
class WordIndex:
    """Index word records by normalized text for O(1) lookup.

    Replaces the O(n*m) _find_word_id linear scan used in the previous
    implementation. Also provides spatial queries by bbox.
    """

    def __init__(self, word_records):
        self._by_text: Dict[str, List[Tuple[str, List[float]]]] = {}
        self._by_id: Dict[str, Tuple[str, List[float]]] = {}
        self._used: Set[str] = set()

        for wr in word_records:
            key = wr.text.strip().lower()
            self._by_text.setdefault(key, []).append((wr.word_id, list(wr.bbox)))
            self._by_id[wr.word_id] = (wr.text, list(wr.bbox))

    def find(self, needle: str) -> Tuple[Optional[str], List[float]]:
        """Return first unused (word_id, bbox) matching needle (case-insensitive, substring). Marks as used."""
        needle_l = needle.strip().lower()
        if not needle_l:
            return None, []

        # Exact match first
        if needle_l in self._by_text:
            for wid, bbox in self._by_text[needle_l]:
                if wid not in self._used:
                    self._used.add(wid)
                    return wid, bbox

        # Substring match (needle in word text or word text in needle)
        for key, entries in self._by_text.items():
            if needle_l in key or key in needle_l:
                for wid, bbox in entries:
                    if wid not in self._used:
                        self._used.add(wid)
                        return wid, bbox

        return None, []

    def lookup(self, needle: str) -> Tuple[Optional[str], List[float]]:
        """Return first (word_id, bbox) matching needle WITHOUT marking as used.

        Use for section detection where we want to locate words but not consume
        them for later field extraction.
        """
        needle_l = needle.strip().lower()
        if not needle_l:
            return None, []

        if needle_l in self._by_text:
            return self._by_text[needle_l][0]

        for key, entries in self._by_text.items():
            if needle_l in key or key in needle_l:
                return entries[0]

        return None, []

    def mark_used(self, word_id: str) -> None:
        self._used.add(word_id)

    def is_used(self, word_id: str) -> bool:
        return word_id in self._used


# ---------------------------------------------------------------------------
# Date parsing with memoization
# ---------------------------------------------------------------------------
_date_cache: Dict[str, Optional[date]] = {}


def _parse_date_cached(value: str) -> Optional[date]:
    """Parse a date string with memoization to avoid re-parsing duplicates."""
    if value in _date_cache:
        return _date_cache[value]
    result = _parse_date_raw(value)
    _date_cache[value] = result
    return result


def _parse_date_raw(value: str) -> Optional[date]:
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
            return datetime.strptime(value.strip(), fmt)
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Internal Line dataclass for line-level structure detection
# ---------------------------------------------------------------------------
@dataclass
class Line:
    """A line of text with typography metadata."""
    text: str
    bbox: List[float] = field(default_factory=list)
    size_max: Optional[float] = None
    size_median: Optional[float] = None
    bold_ratio: Optional[float] = None
    caps_ratio: Optional[float] = None
    x0: Optional[float] = None
    gap_before: Optional[float] = None
    page: int = 1
    line_class: str = "BODY"  # HEADING | BODY | LIST_ITEM | PAGE_FURNITURE
    word_ids: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Data structures (public API)
# ---------------------------------------------------------------------------
@dataclass
class DateInterval:
    """A date range with start/end and optional 'Present' marker."""
    start: Optional[date] = None
    end: Optional[date] = None
    is_present: bool = False  # True if end is "Present"
    raw_text: str = ""
    word_ids: List[str] = field(default_factory=list)
    bbox: List[float] = field(default_factory=list)


@dataclass
class ManipulationFlag:
    """M1-M5 manipulation flag with evidence."""
    flag_id: str
    rule_id: str
    evidence: str
    severity: str  # High / Medium / Low
    bbox: List[float] = field(default_factory=list)
    word_ids: List[str] = field(default_factory=list)


@dataclass
class StructureResult:
    """Complete Stage 4 output (Section 8.8)."""
    sections: List[SchemaSection]
    fields: List[SchemaField]
    date_intervals: List[DateInterval]
    labels: List[Dict[str, str]]           # [{"field": "...", "label": "FACT"}]
    rule_flags: List[str]                  # R1-R11, F1-F6, J1-J3
    manipulation_flags: List[ManipulationFlag]
    conservation_ledger: List[Dict]        # append-only audit entries
    record_root: str                       # hash of sealed record
    pii_ref: str                           # pointer to PII storage (not the PII itself)
    track: str                             # "resume" or "job_description"
    lines: List[Line] = field(default_factory=list)  # line-level structure (Section 8.8)


# ---------------------------------------------------------------------------
# Section detection: line-based with typography + gap cues (Section 8.8)
# ---------------------------------------------------------------------------
def _is_heading_line(line: Line, body_median_size: Optional[float], cfg) -> bool:
    """Decide if a line is a heading using 2-3 signals (never just one).

    Signals:
    1. Alias match (strong)
    2. size_max >= 1.2 * body_median_size (if sizes known)
    3. bold_ratio >= 0.6 (if known)
    4. Caps / Title-case (if known)
    5. Short line (<= 60 chars)
    6. gap_before > gap_ratio * line_pitch (fallback when sizes unknown)

    Returns True if at least 2 signals fire.
    """
    text_l = line.text.strip().lower()
    if not text_l:
        return False

    signals = 0

    # Signal 1: Alias match (strong)
    alias_match = False
    canonical = _ALIAS_TO_CANONICAL.get(text_l)
    if not canonical:
        for alias, canon in _ALIAS_TO_CANONICAL.items():
            if text_l == alias or text_l.startswith(alias + " ") or text_l.startswith(alias + ":"):
                canonical = canon
                alias_match = True
                break
    if canonical:
        signals += 2  # alias match counts double as "strong" signal

    # Signal 2: Size ratio
    if line.size_max is not None and body_median_size is not None and body_median_size > 0:
        if line.size_max >= cfg.heading_size_ratio * body_median_size:
            signals += 1

    # Signal 3: Bold ratio
    if line.bold_ratio is not None and line.bold_ratio >= 0.6:
        signals += 1

    # Signal 4: Caps / Title-case
    text_stripped = line.text.strip()
    if text_stripped:
        alpha_chars = [c for c in text_stripped if c.isalpha()]
        if alpha_chars:
            caps_count = sum(1 for c in alpha_chars if c.isupper())
            caps_ratio_line = caps_count / len(alpha_chars)
            if caps_ratio_line >= 0.7 or text_stripped == text_stripped.title():
                signals += 1
                line.caps_ratio = caps_ratio_line

    # Signal 5: Short line (<= 60 chars)
    if len(text_stripped) <= 60:
        signals += 1

    # Signal 6: Gap before > gap_ratio * line_pitch (fallback)
    if line.gap_before is not None and line.size_max is None and line.bold_ratio is None:
        # Gap is the fallback when size/bold are None (OCR)
        line_pitch = cfg.gap_ratio * 12.0  # default ~12pt line pitch
        if line.gap_before > line_pitch * cfg.gap_ratio:
            signals += 1

    return signals >= 2


def _build_lines(word_records, cfg) -> List[Line]:
    """Group word_records by page + rounded y0 into Line objects.

    Computes per-line: text, bbox, size_max, size_median, bold_ratio,
    caps_ratio, x0, gap_before, page.
    Also computes line_pitch = median Δy between consecutive lines.
    """
    # Group by (page, rounded y0)
    line_dict: Dict[Tuple[int, int], List] = {}
    for wr in word_records:
        page = getattr(wr, "page", 1)
        y0 = round(wr.bbox[1] / 10) * 10  # round to nearest 10pt line bucket
        key = (page, y0)
        line_dict.setdefault(key, []).append(wr)

    # Sort keys by (page, y0)
    sorted_keys = sorted(line_dict.keys(), key=lambda k: (k[0], k[1]))

    lines: List[Line] = []
    prev_y1: Optional[float] = None
    prev_page: Optional[int] = None
    y_positions: List[float] = []

    for key in sorted_keys:
        page, y0_bucket = key
        wrs = sorted(line_dict[key], key=lambda w: round(w.bbox[0]))

        # Merge text left-to-right
        text_parts = [w.text for w in wrs if w.text.strip()]
        text = " ".join(text_parts)

        # Bounding box
        x0 = min(w.bbox[0] for w in wrs)
        y0 = min(w.bbox[1] for w in wrs)
        x1 = max(w.bbox[2] for w in wrs)
        y1 = max(w.bbox[3] for w in wrs)
        bbox = [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)]

        # Typography
        sizes = [w.size for w in wrs if w.size is not None]
        size_max = max(sizes) if sizes else None
        size_median = sorted(sizes)[len(sizes) // 2] if sizes else None

        bold_count = sum(1 for w in wrs if w.bold)
        bold_ratio = bold_ratio = bold_count / len(wrs) if wrs else None

        # Caps ratio
        alpha_chars = [c for c in text if c.isalpha()]
        caps_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars) if alpha_chars else None

        # Gap before
        gap_before = None
        if prev_y1 is not None and page == prev_page:
            gap_before = round(y0 - prev_y1, 1)

        line = Line(
            text=text,
            bbox=bbox,
            size_max=size_max,
            size_median=size_median,
            bold_ratio=bold_ratio,
            caps_ratio=caps_ratio,
            x0=round(x0, 1),
            gap_before=gap_before,
            page=page,
            word_ids=[w.word_id for w in wrs],
        )
        lines.append(line)
        y_positions.append(y0)
        prev_y1 = y1
        prev_page = page

    # Compute line_pitch = median Δy between consecutive lines on same page
    page_y_positions: Dict[int, List[float]] = {}
    for line in lines:
        page_y_positions.setdefault(line.page, []).append(line.bbox[1])

    line_pitches: List[float] = []
    for page, ys in page_y_positions.items():
        if len(ys) >= 2:
            ys_sorted = sorted(ys)
            deltas = [ys_sorted[i] - ys_sorted[i - 1] for i in range(1, len(ys_sorted)) if ys_sorted[i] - ys_sorted[i - 1] > 0]
            if deltas:
                line_pitches.append(sorted(deltas)[len(deltas) // 2])

    line_pitch = sorted(line_pitches)[len(line_pitches) // 2] if line_pitches else 12.0

    # Compute body_median_size from all lines
    all_sizes = [l.size_median for l in lines if l.size_median is not None]
    body_median_size = sorted(all_sizes)[len(all_sizes) // 2] if all_sizes else None

    # Assign gap_before and line_pitch to each line
    for line in lines:
        # Recompute gap_before more precisely using previous line's y1
        pass  # already computed above

    # Set body_median_size on config temporarily? No, just pass to heading detection
    return lines, body_median_size, line_pitch


def _classify_lines(lines: List[Line], body_median_size: Optional[float], cfg) -> List[Line]:
    """Classify each line as HEADING, BODY, LIST_ITEM, or PAGE_FURNITURE."""
    # First pass: detect headings
    for line in lines:
        if _is_heading_line(line, body_median_size, cfg):
            line.line_class = "HEADING"

    # Second pass: detect PAGE_FURNITURE (same text at same position on >= 2 pages)
    from collections import Counter
    text_pos_counter: Dict[Tuple[str, int], int] = Counter()
    for line in lines:
        key = (line.text.strip().lower(), round(line.x0 or 0))
        text_pos_counter[key] += 1

    for line in lines:
        key = (line.text.strip().lower(), round(line.x0 or 0))
        if text_pos_counter[key] >= 2:
            line.line_class = "PAGE_FURNITURE"

    # Third pass: detect LIST_ITEM (lines starting with bullet/number/dash)
    list_marker_re = re.compile(r"^[\d\)\.\-]\s+|^[\u2022\u2013\u2014]\s+")
    for line in lines:
        if line.line_class == "HEADING" or line.line_class == "PAGE_FURNITURE":
            continue
        if list_marker_re.match(line.text.strip()):
            line.line_class = "LIST_ITEM"

    return lines


def _segment_sections(lines: List[Line], cfg) -> Tuple[List[SchemaSection], List[str]]:
    """Segment lines into sections starting at each heading OR wide gap.

    Returns (sections, rule_flags).
    """
    sections: List[SchemaSection] = []
    rule_flags: List[str] = []
    seen_sections: Set[str] = set()

    current: Optional[SchemaSection] = None
    current_line_ids: List[str] = []

    for line in lines:
        # Decide if this line starts a new section
        start_new = False

        if line.line_class == "HEADING":
            start_new = True
        elif line.line_class != "PAGE_FURNITURE" and line.gap_before is not None:
            # Wide gap → new section (if not already a heading)
            line_pitch = 12.0  # default
            if line.gap_before > cfg.gap_ratio * line_pitch:
                start_new = True

        if start_new:
            # Save previous section
            if current:
                sections.append(current)

            # Determine section name from heading line alias
            text_l = line.text.strip().lower()
            canonical = _ALIAS_TO_CANONICAL.get(text_l)
            if not canonical:
                for alias, canon in _ALIAS_TO_CANONICAL.items():
                    if text_l == alias or text_l.startswith(alias + " ") or text_l.startswith(alias + ":"):
                        canonical = canon
                        break

            if canonical:
                # R2: Duplicate section
                if canonical in seen_sections:
                    rule_flags.append(RULE_R2)
                seen_sections.add(canonical)
                section_name = canonical
            else:
                section_name = text_l[:40]  # truncate unknown headings

            current = SchemaSection(
                name=section_name,
                text=line.text,
                start_line=0,
                end_line=0,
                heading_line_id=line.word_ids[0] if line.word_ids else None,
                line_class=line.line_class,
            )
            # Attach word ids from heading line
            if line.word_ids:
                current.word_ids.extend(line.word_ids)
                current.bbox = list(line.bbox)
        else:
            # Append to current section
            if current is not None:
                current.text += " " + line.text
                current.end_line = 0  # placeholder
                if line.word_ids:
                    current.word_ids.extend(line.word_ids)
                    # Extend bbox
                    if line.bbox and len(line.bbox) >= 4:
                        if not current.bbox:
                            current.bbox = list(line.bbox)
                        else:
                            current.bbox[0] = min(current.bbox[0], line.bbox[0])
                            current.bbox[1] = min(current.bbox[1], line.bbox[1])
                            current.bbox[2] = max(current.bbox[2], line.bbox[2])
                            current.bbox[3] = max(current.bbox[3], line.bbox[3])

    if current:
        sections.append(current)

    # R3: Empty sections
    for s in sections:
        if len(s.text.strip()) <= len(s.name) + 2:
            rule_flags.append(RULE_R3)

    return sections, rule_flags


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------
def extract_structure(clean_text: str, word_records, track: str = "resume", uploaded_at: Optional[float] = None) -> StructureResult:
    """Extract structured data from clean text + word records.

    Optimizations over previous implementation:
    - WordIndex: O(1) text→word_id lookup (was O(n*m) linear scan)
    - Position-aware section detection using bbox y-coordinates
    - Memoized date parsing
    - Conservation ledger for audit trail
    - Date intervals with 'Present' → as_of handling
    - Rule families R1-R11, F1-F6, J1-J3
    - Manipulation flags M1-M5
    - Labels: CONTRADICTION/CONFLICT/FACT/NOT_EVALUATED
    - Line-level structure with typography + gap cues (Section 8.8), gated behind
      config.structure_layout_enabled
    """
    ledger: List[Dict] = []
    rule_flags: List[str] = []
    manipulation_flags: List[ManipulationFlag] = []
    labels: List[Dict[str, str]] = []

    def ledger_entry(event: str, payload: dict) -> None:
        entry = {"event": event, "payload": payload}
        ledger.append(entry)

    # Build O(1) word index
    index = WordIndex(word_records)

    # Determine as_of date for "Present" handling
    as_of_date: Optional[date] = None
    if uploaded_at:
        try:
            as_of_date = datetime.fromtimestamp(uploaded_at).date()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Line building + section detection
    # ------------------------------------------------------------------
    lines: List[Line] = []
    body_median_size: Optional[float] = None
    line_pitch: float = 12.0

    if config.structure_layout_enabled and word_records:
        lines, body_median_size, line_pitch = _build_lines(word_records, config)
        lines = _classify_lines(lines, body_median_size, config)
        sections, seg_rule_flags = _segment_sections(lines, cfg=config)
        rule_flags.extend(seg_rule_flags)
    else:
        # Fallback: original line-based detection from clean_text
        lines_text = [ln.strip() for ln in clean_text.splitlines() if ln.strip()]
        sections: List[SchemaSection] = []
        current: Optional[SchemaSection] = None
        seen_sections: Set[str] = set()

        for idx, line_text in enumerate(lines_text):
            is_header, canonical = _is_section_header_legacy(line_text)

            if is_header:
                if canonical in seen_sections:
                    rule_flags.append(RULE_R2)
                seen_sections.add(canonical)

                if current:
                    sections.append(current)
                current = SchemaSection(
                    name=canonical,
                    text=line_text,
                    start_line=idx,
                    end_line=idx,
                )
            else:
                if current is not None:
                    current.text += " " + line_text
                    current.end_line = idx

        if current:
            sections.append(current)

        ledger_entry("sections_extracted", {"count": len(sections), "names": [s.name for s in sections]})

    # ------------------------------------------------------------------
    # Field extraction with WordIndex (O(1) lookups)
    # ------------------------------------------------------------------
    fields: List[SchemaField] = []

    def add_field(name: str, value: str, needle: str) -> None:
        wid, bbox = index.find(needle)
        fields.append(SchemaField(
            name=name,
            value=value,
            word_ids=[wid] if wid else [],
            bbox=bbox,
        ))
        ledger_entry("field_extracted", {"name": name, "value": value, "word_id": wid})

    for m in EMAIL_RE.finditer(clean_text):
        add_field("email", m.group(0), m.group(0))

    for m in PHONE_RE.finditer(clean_text):
        add_field("phone", m.group(0), m.group(0))

    for m in URL_RE.finditer(clean_text):
        add_field("url", m.group(0), m.group(0))

    for m in LINKEDIN_RE.finditer(clean_text):
        add_field("linkedin", m.group(0), m.group(0))

    for m in GITHUB_RE.finditer(clean_text):
        add_field("github", m.group(0), m.group(0))

    # ------------------------------------------------------------------
    # Date interval extraction
    # ------------------------------------------------------------------
    date_intervals: List[DateInterval] = []
    date_fields: List[Tuple[SchemaField, Optional[date]]] = []

    for m in DATE_RE.finditer(clean_text):
        raw = m.group(0)
        parsed = _parse_date_cached(raw)
        wid, bbox = index.find(raw)
        field = SchemaField(
            name="date",
            value=raw,
            word_ids=[wid] if wid else [],
            bbox=bbox,
        )
        fields.append(field)
        date_fields.append((field, parsed))
        date_intervals.append(DateInterval(
            start=parsed,
            end=None,
            is_present=False,
            raw_text=raw,
            word_ids=[wid] if wid else [],
            bbox=bbox,
        ))

    # Handle "Present" as end date → as_of
    present_pattern = re.compile(r"\bpresent\b", re.IGNORECASE)
    for m in present_pattern.finditer(clean_text):
        m_start = m.start()
        preceding_dates = [
            (di, idx) for idx, di in enumerate(date_intervals)
            if clean_text.find(di.raw_text, 0, m_start) != -1
        ]
        if preceding_dates and as_of_date:
            preceding_dates.sort(key=lambda x: clean_text.find(x[0].raw_text, 0, m_start))
            di, _ = preceding_dates[-1]
            di.end = as_of_date
            di.is_present = True

    # R8: Future dates
    today = date.today()
    for field, parsed in date_fields:
        if parsed and parsed > today:
            rule_flags.append(RULE_R8)
            field.name = "date:future"

    # R9: End before start (consecutive dates)
    parsed_sorted = sorted(
        [(f, d) for f, d in date_fields if d],
        key=lambda x: x[1],
    )
    for i in range(1, len(parsed_sorted)):
        if parsed_sorted[i][1] < parsed_sorted[i - 1][1]:
            rule_flags.append(RULE_R9)
            parsed_sorted[i][0].name = "date:end_before_start"

    # R11: Inconsistent date formats
    formats_seen = set()
    for m in DATE_RE.finditer(clean_text):
        raw = m.group(0)
        if re.match(r"\d{4}[/-]", raw):
            formats_seen.add("ISO")
        elif re.match(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", raw):
            formats_seen.add("DMY/MDY")
        elif re.match(r"[A-Za-z]+\s+\d{4}", raw):
            formats_seen.add("MonthYear")
    if len(formats_seen) > 1:
        rule_flags.append(RULE_R11)

    ledger_entry("fields_extracted", {"count": len(fields), "date_intervals": len(date_intervals)})

    # ------------------------------------------------------------------
    # Labels (Section 8.4)
    # ------------------------------------------------------------------
    label_map: Dict[str, str] = {}
    for field in fields:
        if field.name.startswith("date:"):
            label_map[field.value] = LABEL_CONFLICT
        elif field.name in ("email", "phone", "linkedin", "github", "url"):
            label_map[field.value] = LABEL_FACT
        else:
            label_map[field.value] = LABEL_NOT_EVALUATED

    labels = [{"field": k, "label": v} for k, v in label_map.items()]

    # ------------------------------------------------------------------
    # Manipulation flags M1-M5 (from Stage 2 findings passed via word_records.flags)
    # ------------------------------------------------------------------
    for wr in word_records:
        for flag in wr.flags:
            if "invisible" in flag.lower() or "hidden" in flag.lower():
                manipulation_flags.append(ManipulationFlag(
                    flag_id=FLAG_M1,
                    rule_id=FLAG_M1,
                    evidence=f"Word '{wr.text}' flagged as {flag}",
                    severity="High",
                    bbox=list(wr.bbox),
                    word_ids=[wr.word_id],
                ))
            elif "remap" in flag.lower() or "glyph" in flag.lower():
                manipulation_flags.append(ManipulationFlag(
                    flag_id=FLAG_M2,
                    rule_id=FLAG_M2,
                    evidence=f"Word '{wr.text}' has remapped glyph",
                    severity="High",
                    bbox=list(wr.bbox),
                    word_ids=[wr.word_id],
                ))
            elif "overlap" in flag.lower():
                manipulation_flags.append(ManipulationFlag(
                    flag_id=FLAG_M3,
                    rule_id=FLAG_M3,
                    evidence=f"Word '{wr.text}' has overlapping bbox",
                    severity="High",
                    bbox=list(wr.bbox),
                    word_ids=[wr.word_id],
                ))

    ledger_entry("manipulation_flags", {"count": len(manipulation_flags)})

    # ------------------------------------------------------------------
    # Track-specific rules
    # ------------------------------------------------------------------
    if track == "job_description":
        # J1: Missing requirements section
        if not any(s.name == "skills" for s in sections):
            rule_flags.append(RULE_J1)
        # J2: Missing responsibilities
        if not any(s.name in ("experience",) for s in sections):
            rule_flags.append(RULE_J2)
        # J3: Vague qualifications (heuristic: skills section very short)
        skills_sec = next((s for s in sections if s.name == "skills"), None)
        if skills_sec and len(skills_sec.text.split()) < 10:
            rule_flags.append(RULE_J3)

    # R1: Missing required sections (resume track)
    if track == "resume":
        has_contact = any(s.name == "contact" for s in sections)
        has_experience = any(s.name == "experience" for s in sections)
        if not has_contact:
            rule_flags.append(RULE_R1)
        if not has_experience:
            rule_flags.append(RULE_R1)

    ledger_entry("rule_flags", {"count": len(rule_flags), "flags": rule_flags})

    # ------------------------------------------------------------------
    # Seal: record_root + pii_ref
    # ------------------------------------------------------------------
    record_payload = {
        "sections": [s.model_dump() for s in sections],
        "fields": [f.model_dump() for f in fields],
        "date_intervals": [
            {
                "start": di.start.isoformat() if di.start else None,
                "end": di.end.isoformat() if di.end else None,
                "is_present": di.is_present,
                "raw_text": di.raw_text,
            }
            for di in date_intervals
        ],
        "rule_flags": rule_flags,
        "manipulation_flags": [
            {"flag_id": mf.flag_id, "rule_id": mf.rule_id, "evidence": mf.evidence, "severity": mf.severity}
            for mf in manipulation_flags
        ],
        "labels": labels,
        "track": track,
        "lines": [
            {
                "text": l.text,
                "bbox": l.bbox,
                "size_max": round(l.size_max, 1) if l.size_max is not None else None,
                "size_median": round(l.size_median, 1) if l.size_median is not None else None,
                "bold_ratio": round(l.bold_ratio, 2) if l.bold_ratio is not None else None,
                "caps_ratio": round(l.caps_ratio, 2) if l.caps_ratio is not None else None,
                "x0": round(l.x0, 1) if l.x0 is not None else None,
                "gap_before": round(l.gap_before, 1) if l.gap_before is not None else None,
                "page": l.page,
                "line_class": l.line_class,
                "word_ids": l.word_ids,
            }
            for l in lines
        ],
    }
    record_root = record_hash(record_payload)

    # PII ref: hash of PII fields only (pointer to encrypted PII store, not the PII itself)
    pii_fields = [f for f in fields if f.name in ("email", "phone", "linkedin", "github")]
    pii_payload = {
        f.name: f.value for f in pii_fields
    }
    pii_ref = hashlib.sha256(
        (track + "|" + hashlib.sha256(
            __import__("json").dumps(pii_payload, sort_keys=True).encode()
        ).hexdigest()).encode()
    ).hexdigest()[:32]

    return StructureResult(
        sections=sections,
        fields=fields,
        date_intervals=date_intervals,
        labels=labels,
        rule_flags=rule_flags,
        manipulation_flags=manipulation_flags,
        conservation_ledger=ledger,
        record_root=record_root,
        pii_ref=pii_ref,
        track=track,
        lines=lines,
    )


# ---------------------------------------------------------------------------
# Legacy section header detection (fallback when structure_layout disabled)
# ---------------------------------------------------------------------------
def _is_section_header_legacy(line_text: str) -> Tuple[bool, str]:
    """Detect if a line is a section header using alias matching."""
    line_l = line_text.strip().lower()
    if not line_l:
        return False, ""

    canonical = _ALIAS_TO_CANONICAL.get(line_l)
    if not canonical:
        for alias, canon in _ALIAS_TO_CANONICAL.items():
            if line_l == alias or line_l.startswith(alias + " ") or line_l.startswith(alias + ":"):
                canonical = canon
                break

    if not canonical:
        return False, ""

    is_short = len(line_text.strip()) <= 60
    if is_short:
        return True, canonical
    return False, ""
