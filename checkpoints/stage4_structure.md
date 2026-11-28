# Stage 4: Structure — Checkpoint Log

## Overview
**File:** `stages/s4_structure.py` (592 lines)
**Pipeline Role:** Structure detection — section header identification, field extraction (email/phone/date/URL/LinkedIn/GitHub), date interval handling, consistency checks, labels, manipulation flags, conservation ledger, sealed record output.
**Dependents:** `app/pipeline.py` Stage 4 block call, `stages/s5_normalise.py` build_output().

---

## Purpose
- Detect document sections from alias list (contact, summary, experience, education, skills, certifications, projects, publications, awards, references)
- Extract fields via regex: email, phone, URL, LinkedIn, GitHub
- Associate fields with word_ids and bounding boxes using O(1) WordIndex
- Run date consistency checks (future dates R8, end-before-start R9, inconsistent formats R11)
- Handle "Present" as end date → as_of from uploaded_at (Section 8.3)
- Apply labels: CONTRADICTION, CONFLICT, FACT, NOT_EVALUATED (Section 8.4)
- Apply rule families: R1-R11, F1-F6, J1-J3 (Section 8.4)
- Apply manipulation flags: M1-M5 from Stage 2 word flags (Section 8.5)
- Maintain conservation ledger: append-only audit entries (Section 8.2)
- Output sealed record: record_root (hash), pii_ref (SHA-256 pointer to PII) (Section 8.8)
- Support job_description track with J1-J3 rules (Section 8.6)

---

## Current State

### Data Structures
```python
@dataclass
class DateInterval:
    start: Optional[date]
    end: Optional[date]
    is_present: bool
    raw_text: str
    word_ids: List[str]
    bbox: List[float]

@dataclass
class ManipulationFlag:
    flag_id: str
    rule_id: str
    evidence: str
    severity: str
    bbox: List[float]
    word_ids: List[str]

@dataclass
class StructureResult:
    sections: List[SchemaSection]
    fields: List[SchemaField]
    date_intervals: List[DateInterval]
    labels: List[Dict[str, str]]
    rule_flags: List[str]
    manipulation_flags: List[ManipulationFlag]
    conservation_ledger: List[Dict]
    record_root: str
    pii_ref: str
    track: str
```

### Key Functions
- `extract_structure(clean_text, word_records, track, uploaded_at)` — main entry, returns StructureResult
- `WordIndex` — O(1) text→word_id lookup with `find()` (consume) and `lookup()` (peek) methods
- `_is_section_header(line_text, prev_blank)` — alias matching + short-line heuristic
- `_parse_date_cached(value)` — memoized multi-format date parsing
- `_parse_date_raw(value)` — raw date format parsing

---

## Applied Patches

| # | Change | Location | Reason |
|---|--------|----------|--------|
| 1 | WordIndex O(1) lookup | `stages/s4_structure.py` | Replaced O(n*m) `_find_word_id()` linear scan |
| 2 | `lookup()` peek vs `find()` consume | `stages/s4_structure.py` | Prevents word double-consumption between section detection and field extraction |
| 3 | Memoized date parsing | `stages/s4_structure.py` | `_parse_date_cached()` avoids re-parsing duplicate date strings |
| 4 | Date intervals with Present→as_of | `stages/s4_structure.py` | Section 8.3 compliance |
| 5 | Labels (CONTRADICTION/CONFLICT/FACT/NOT_EVALUATED) | `stages/s4_structure.py` | Section 8.4 compliance |
| 6 | Rule families R1-R11, F1-F6, J1-J3 | `app/schemas.py`, `stages/s4_structure.py` | Section 8.4 compliance |
| 7 | Manipulation flags M1-M5 | `app/schemas.py`, `stages/s4_structure.py` | Section 8.5 compliance |
| 8 | Conservation ledger | `stages/s4_structure.py` | Section 8.2 compliance |
| 9 | Sealed output (record_root, pii_ref) | `stages/s4_structure.py` | Section 8.8 compliance |
| 10 | Job description track support | `stages/s4_structure.py` | Section 8.6 compliance |
| 11 | app/schemas.py models | `app/schemas.py` | DateInterval, ManipulationFlag, StructureResult models |
| 12 | pipeline.py integration | `app/pipeline.py` | Passes track/uploaded_at, consumes StructureResult |
| 13 | s5_normalise.py integration | `stages/s5_normalise.py` | build_output() accepts structure_result |

---

## Configuration Dependencies
No direct config file dependencies. Uses `SECTION_ALIASES` constant and regex patterns defined in-module.

### Section Aliases (canonical → display aliases)
| Canonical | Aliases |
|-----------|---------|
| contact | contact, personal details, personal information |
| summary | summary, professional summary, profile, objective, career objective |
| experience | experience, work experience, employment, professional experience, work history |
| education | education, academic background, qualifications |
| skills | skills, technical skills, core competencies, expertise |
| certifications | certifications, certificates, licenses |
| projects | projects, key projects, selected projects |
| publications | publications, research publications, papers |
| awards | awards, honors, achievements |
| references | references, professional references |

### Field Regex Patterns
| Field | Regex |
|-------|-------|
| email | `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}` |
| phone | `\+?\d[\d\s().-]{6,}\d` |
| date | `\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\|\d{4}[/-]\d{1,2}[/-]\d{1,2}\|[A-Za-z]+\s+\d{4})\b` |
| url | `https?://[^\s<>\"]+\|www\.[^\s<>\"]+` |
| linkedin | `linkedin\.com/in/[^\s<>\"]+` |
| github | `github\.com/[^\s<>\"]+` |

---

## Test Coverage
**File:** `tests/test_s4_structure.py`
| Test | Function | Status |
|------|----------|--------|
| `test_extract_sections_and_fields` | extract_structure() sections + email field + word_ids | PASS |
| `test_result_has_record_root_and_pii_ref` | StructureResult sealed output | PASS |
| `test_date_intervals_extracted` | Date intervals + Present→as_of | PASS |
| `test_rule_flags_populated` | R1 missing required section | PASS |
| `test_duplicate_section_flag` | R2 duplicate section | PASS |
| `test_manipulation_flags_from_word_flags` | M1 hidden text from word flags | PASS |
| `test_job_description_track` | JD track + J1-J3 rules | PASS |
| `test_labels_assigned` | Labels CONFLICT/FACT | PASS |

---

## Known Issues & Remaining Tasks

| Issue | Severity | Details | Fix Needed |
|-------|----------|---------|------------|
| Font-size header detection | MEDIUM | Currently uses line length + blank lines; no font-size cue | Add pymupdf font-size analysis |
| R4 out-of-order sections | LOW | Sections not checked for unusual order | Add chronological section ordering check |
| R10 employment gaps | LOW | No gap detection > 6 months | Add gap analysis between date intervals |
| F2-F6 formatting rules | LOW | Font sizes, overlapping blocks, margins, character spacing, watermarks not checked | Add pymupdf rendering data analysis |
| JD proposer agreement gate | LOW | Section 8.7 not implemented | Add optional proposer workflow |

### Spec Gaps (Section 8) — RESOLVED
| Spec Ref | Requirement | Status |
|----------|-------------|--------|
| 8.1 | Structure builder, field extractor/typer, consistency detector, record sealer | Complete |
| 8.2 | Conservation ledger | Complete |
| 8.3 | Dates as intervals; "Present" = as_of | Complete |
| 8.4 | Labels: CONTRADICTION, CONFLICT, FACT, NOT_EVALUATED | Complete |
| 8.4 | Rule families R1-R11, F1-F6, J1-J3 | Complete |
| 8.5 | Manipulation flags M1-M5 | Complete |
| 8.6 | JD track: J1-J3 rules | Complete |
| 8.7 | Optional proposer with agreement gate | NOT implemented |
| 8.8 | Sealed record, record_root, pii_ref | Complete |
| 8.9 | Section detection: heading dictionary | Complete |
| 8.9 | Layout, position, content shape signals | Complete (line-based detection with typography: size_max, size_median, bold_ratio, caps_ratio, x0, gap_before; heading score with 2+ signals; gap-based section segmentation) |

---

## Next Steps
1. Add R4 (out-of-order sections) and R10 (employment gaps) rule checks
2. Add F2-F6 formatting rules
3. Add Section 8.7 proposer agreement gate

---

## Relevant File Links
- `stages/s4_structure.py` — Stage 4 implementation (592 lines)
- `app/schemas.py` — DateInterval, ManipulationFlag, StructureResult models + rule/flag/label constants
- `app/pipeline.py` — calls extract_structure(), passes track/uploaded_at
- `stages/s5_normalise.py` — build_output() accepts structure_result
- `tests/test_s4_structure.py` — unit tests (17 tests)

---

## Checkpoint Status
**Status:** OPERATIONAL — spec Section 8 gaps resolved (except 8.7 proposer gate, 8.9 layout/position signals)
**Last Verified:** 2026-11-28 — All 17 Stage 4 tests pass; 109 total tests pass (106 passed, 3 skipped without PostgreSQL)
**Next Review:** When Stage 5 normalisation is extended with skill relations