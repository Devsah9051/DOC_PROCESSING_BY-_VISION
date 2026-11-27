# Stage 4: Structure — Checkpoint Log

## Overview
**File:** `stages/s4_structure.py`
**Pipeline Role:** Structure detection — section header identification, field extraction (email/phone/date), consistency checks.
**Dependents:** `app/pipeline.py` Stage 4 block call.

---

## Purpose
- Detect document sections from alias list
- Extract fields via regex: email, phone, date
- Associate fields with word_ids and bounding boxes
- Run date consistency checks (future dates, end-before-start)
- Return `(List[Section], List[Field])`

---

## Current State

### Data Structures
```python
@dataclass
class Field:
    name: str
    value: str
    word_ids: List[str]
    bbox: List[float]

@dataclass
class Section:
    name: str
    text: str
    word_ids: List[str]
    bbox: List[float]
    start_line: int
    end_line: int
```

### Key Functions
- `extract_structure(clean_text, word_records)` — main entry
- `_find_word_id(word_records, needle, used)` — fuzzy word matching
- `_check_dates(fields)` — date consistency validation
- `_parse_date(value)` — multi-format date parsing

---

## Applied Patches

| # | Change | Location | Reason |
|---|--------|----------|--------|
| 1 | Separated `used_word_ids` sets | `extract_structure()` | Previously shared between sections and fields caused empty `word_ids` on fields |

---

## Configuration Dependencies
No direct config file dependencies. Uses `SECTION_ALIASES` constant and regex patterns defined in-module.

### Section Aliases
summary, professional summary, objective, experience, work experience, employment, professional experience, education, skills, technical skills, certifications, projects, publications, contact, personal details

### Field Regex Patterns
| Field | Regex |
|-------|-------|
| email | `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}` |
| phone | `\+?\d[\d\s().-]{6,}\d` |
| date | `\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\|\d{4}[/-]\d{1,2}[/-]\d{1,2}\|[A-Za-z]+\s+\d{4})\b` |

---

## Test Coverage
**File:** `tests/test_s4_structure.py`
| Test | Function | Status |
|------|----------|--------|
| `test_extract_sections_and_fields` | extract_structure() sections + email field | PASS |

---

## Known Issues & Remaining Tasks

| Issue | Severity | Details | Fix Needed |
|-------|----------|---------|------------|
| `used_word_ids` shared | FIXED | Was causing empty word_ids on email field | RESOLVED |
| Section detection exact alias | MEDIUM | "Experience" matches; "Work History" doesn't | Acceptable for Phase 1 |
| Date parsing limited formats | MEDIUM | Supports MM/DD/YYYY, DD/MM/YYYY, etc. | Acceptable for Phase 1 |

### Spec Gaps (Section 8)
| Spec Ref | Requirement | Current State | Gap |
|----------|-------------|---------------|-----|
| 8.1 | Structure builder, field extractor/typer | Partial | MISSING consistency detector, record sealer |
| 8.2 | Conservation ledger | NOT implemented | MISSING |
| 8.3 | Dates as intervals; "Present" = as_of | NOT implemented | MISSING |
| 8.4 | Labels: CONTRADICTION, CONFLICT, FACT, NOT_EVALUATED | NOT implemented | MISSING |
| 8.4 | Rule families R1-R11, F1-F6, J1-J3 | NOT implemented | MISSING |
| 8.5 | Manipulation flags M1-M5 | Partial (M1 only) | MISSING M2-M5 |
| 8.6 | JD track: draft requirements, recruiter review, DRS seal | NOT implemented | MISSING |
| 8.7 | Optional proposer with agreement gate | NOT implemented | MISSING |
| 8.9 | Section detection: heading dictionary + layout + position | Partial (aliases only) | MISSING layout/position |

---

## Next Steps
1. Add conservation ledger per Section 8.2
2. Add date interval handling per Section 8.3
3. Add labels and rule families per Section 8.4
4. Add M2-M5 manipulation flags per Section 8.5
5. Add layout/position/content shape signals to section detection

---

## Relevant File Links
- `stages/s4_structure.py` — Stage 4 implementation
- `app/schemas.py` — Section, Field models
- `app/pipeline.py` — calls extract_structure()
- `tests/test_s4_structure.py` — unit tests

---

## Checkpoint Status
**Status:** OPERATIONAL
**Last Verified:** 2026-11-27 — All tests pass
**Next Review:** When section aliases or field types are expanded
