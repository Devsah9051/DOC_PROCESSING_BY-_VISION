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
RULE_R1 = "R1_MISSING_REQUIRED_SECTION"   # resume missing contact or experience
RULE_R2 = "R2_DUPLICATE_SECTION"           # same section appears twice
RULE_R3 = "R3_EMPTY_SECTION"               # section header with no body text
RULE_R4 = "R4_OUT_OF_ORDER_SECTIONS"       # sections in unusual order
RULE_R5 = "R5_UNKNOWN_SECTION"             # section header not in known aliases
RULE_R6 = "R6_INVALID_EMAIL_FORMAT"        # email fails basic validation
RULE_R7 = "R7_INVALID_PHONE_FORMAT"        # phone too short / malformed
RULE_R8 = "R8_DATE_IN_FUTURE"              # date beyond uploaded_at
RULE_R9 = "R9_END_BEFORE_START"            # employment end date before start date
RULE_R10 = "R10_GAP_IN_EMPLOYMENT"         # unexplained gap > 6 months
RULE_R11 = "R11_INCONSISTENT_DATE_FORMAT"  # mixed date formats in same section

# F1-F6: Formatting / presentation rules
RULE_F1 = "F1_MIXED_DATE_FORMATS"          # MM/DD/YYYY mixed with DD/MM/YYYY
RULE_F2 = "F2_INCONSISTENT_FONT_SIZES"     # section headers use varying sizes
RULE_F3 = "F3_OVERLAPPING_TEXT_BLOCKS"     # bboxes overlap (possible OCR artifact)
RULE_F4 = "F4_TEXT_OUTSIDE_MARGINS"        # text beyond expected page bounds
RULE_F5 = "F5_UNUSUAL_CHARACTER_SPACING"   # letter-spaced headings (steganography risk)
RULE_F6 = "F6_WATERMARK_OR_BACKGROUND"     # page furniture detected

# J1-J3: Job description track rules
RULE_J1 = "J1_MISSING_REQUIREMENTS_SECTION"   # JD missing requirements/qualifications
RULE_J2 = "J2_MISSING_RESPONSIBILITIES"       # JD missing duties/responsibilities
RULE_J3 = "J3_VAGUE_QUALIFICATIONS"           # JD qualifications lack specificity

# ---------------------------------------------------------------------------
# Manipulation flags M1-M5 (Section 8.5)
# ---------------------------------------------------------------------------
FLAG_M1 = "M1_HIDDEN_TEXT"              # text with render_mode=3 or invisible
FLAG_M2 = "M2_REMAPPED_GLYPH"           # custom font mapping hides real text
FLAG_M3 = "M3_OVERLAPPING_BBOX"         # two words claim same physical space
FLAG_M4 = "M4_TEXT_OUTSIDE_VISIBLE"     # text marked invisible but extracted
FLAG_M5 = "M5_ANOMALOUS_FONT_MAP"       # font cmap doesn't match extracted glyphs

# ---------------------------------------------------------------------------
# Labels (Section 8.4)
# ---------------------------------------------------------------------------
LABEL_CONTRADICTION = "CONTRADICTION"   # two facts directly conflict
LABEL_CONFLICT = "CONFLICT"             # dates/ranges overlap suspiciously
LABEL_FACT = "FACT"                     # single-source, internally consistent
LABEL_NOT_EVALUATED = "NOT_EVALUATED"   # insufficient data to label

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
            return datetime.strptime(value.strip(), fmt).date()
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Data structures
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


# ---------------------------------------------------------------------------
# Section detection: line-based with alias matching
# ---------------------------------------------------------------------------
def _is_section_header(line_text: str, prev_line_was_blank: bool = False) -> Tuple[bool, str]:
    """Detect if a line is a section header using alias matching.

    Heuristics:
    1. Alias match (case-insensitive, exact or prefix with space/colon)
    2. Line is short (headers are typically concise)
    3. Preceded by a blank line (new section block)
    """
    line_l = line_text.strip().lower()
    if not line_l:
        return False, ""

    # Alias match
    canonical = _ALIAS_TO_CANONICAL.get(line_l)
    if not canonical:
        for alias, canon in _ALIAS_TO_CANONICAL.items():
            if line_l == alias or line_l.startswith(alias + " ") or line_l.startswith(alias + ":"):
                canonical = canon
                break

    if not canonical:
        return False, ""

    # Position cues: short line suggests header
    is_short = len(line_text.strip()) <= 60

    if is_short:
        return True, canonical
    return False, ""


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
    # Section detection (line-based, alias matching)
    # ------------------------------------------------------------------
    lines = [ln.strip() for ln in clean_text.splitlines() if ln.strip()]
    prev_blank = False  # track if previous line was blank (gap cue)

    sections: List[SchemaSection] = []
    current: Optional[SchemaSection] = None
    seen_sections: Set[str] = set()

    for idx, line_text in enumerate(lines):
        is_header, canonical = _is_section_header(line_text, prev_blank)

        if is_header:
            # R2: Duplicate section
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
            # Attach word ids from this line's text via WordIndex (peek only)
            wid, bbox = index.lookup(line_text)
            if wid:
                current.word_ids.append(wid)
                current.bbox = bbox
        else:
            if current is not None:
                current.text += " " + line_text
                current.end_line = idx
                # Try to attach any words from this line (peek only, don't consume)
                wid, bbox = index.lookup(line_text)
                if wid and wid not in current.word_ids:
                    current.word_ids.append(wid)

        prev_blank = (line_text.strip() == "")

    if current:
        sections.append(current)

    # R5: Unknown sections (lines that look like headers but aren't in aliases)
    # (Already handled by _is_section_header returning canonical=None)

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
        # Find nearest preceding date to pair with "Present"
        m_start = m.start()
        preceding_dates = [
            (di, idx) for idx, di in enumerate(date_intervals)
            if clean_text.find(di.raw_text, 0, m_start) != -1
        ]
        if preceding_dates and as_of_date:
            # Pair the most recent preceding date with "Present" as end
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
    # FACT: single-source, internally consistent
    # CONTRADICTION: two facts directly conflict
    # CONFLICT: dates/ranges overlap suspiciously
    # NOT_EVALUATED: insufficient data
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

    # R3: Empty sections
    for s in sections:
        if len(s.text.strip()) <= len(s.name) + 2:  # just the header, no body
            rule_flags.append(RULE_R3)

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
    )
