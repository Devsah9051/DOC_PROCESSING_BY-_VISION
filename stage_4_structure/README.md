# README — Stage 4: Structure

Source specification: EGCA Phase 1 Final Specification rev4, Section 8 ("Stage 4: Structuring"), Section 8.9 (section detection), Section 8.5 (manipulation flags M1-M5).

## Purpose

Stage 4 turns the clean verified text into a tidy, sealed record: name-less identity block, jobs, education, skills, projects, with dates as ranges. Every item points back to the words it came from. It only flags a conflict when completely sure (a month with no day is not a conflict). It never decides if a person is good, and never lets the resume's own words give it orders.

## Modules

| Module | What it does |
|---|---|
| Structure builder | Finds sections and entries, with a conservation ledger: every verified character either placed in a field or listed as unplaced, so nothing silently disappears |
| Field extractor and typer | Pulls out roles, organisations, dates, skills, links and numbers; each keeps its span (block id, start, end) |
| Consistency detector | Applies rules and attaches labels (CONTRADICTION, CONFLICT, FACT, NOT_EVALUATED) |
| Record sealer | Computes record_root and stores identity separately behind pii_ref |

## Dates (8.3)

Dates stored as intervals, not points. "Mar 2022" means the whole month. "Present" means as_of, taken from uploaded_at, never from today's clock, so a re-run gives the same answer. An end month and start month in the same month are not an overlap.

## Labels (8.4)

Labels used only when fully certain. Otherwise item left unlabelled or marked NOT_EVALUATED with a reason:
- CONTRADICTION — two things that cannot both be true even at the most generous reading
- CONFLICT — two things that disagree in a way a reviewer should look at
- FACT — plain extracted statement, no issue
- NOT_EVALUATED — could not be judged (reason: extraction, imprecise, ambiguous, identity, scale_unknown, parse_ocr)

Rule families: R1 to R11 (dates and roles), F1 to F6 (format and field), J1 to J3 (job-description checks).

## Manipulation flags (8.5)

Flags, not labels. They set risk to REVIEW; never reject a candidate; flagged text never turned into a skill claim:
- **M1 INSTRUCTION_LIKE** — text addressed to screener or AI ("ignore previous instructions", "rate this candidate highly"), including visible black-on-white text. Raised by Stage 3 universal scan and carried into record.
- **M2 WRONG_DOCUMENT** — file is not a resume (invoice, form)
- **M3 STUFFING** — long lists of skill words with no context, or repeated keywords
- **M4 UNICODE_ANOMALY** — look-alike characters, zero-width characters, mixed scripts inside a word
- **M5 LINK_MISMATCH** — visible text of a link and its real target differ (link never opened)

M2 to M5 raised in Stage 4. M2 to M5 raise effective risk tier at sealer; post-gate tier never lowered.

## Section detection (8.9)

Section boundaries from four signals used together:
- Versioned heading dictionary (Experience, Work History, Employment; Education; Skills; Projects; Certifications) matched after case and spacing normalisation
- Layout (larger or bolder text, capitals, rule line, white space above)
- Position (first line of a column or frame)
- Content shape (what follows looks like dates, titles or skill list)

Creative headings accepted only if layout and content shape agree on one section type; otherwise text stays UNPLACED with reason UNKNOWN_HEADING. Page-break continuation: section continues across page/column break until next accepted heading. Columns built inside a column in reading order using column_id from Stage 2. Dates in separate column attached to entry on same line band; if two entries tie, date stays UNPLACED rather than guessed.

## Job-description track (8.6)

In Stage 4, rules extract draft requirements, each keeping its original sentence. In Stage 5 they are normalised like any other text. Recruiter reviews with canonical ids visible: edits, adds, approves alternatives. Only then is requirement set sealed as DRS.

## Functional Components

| Component | File | Responsibility |
|---|---|---|
| Section detector | `stages/s4_structure.py` (`extract_structure`) | Alias-dictionary section matching (contact, experience, education, skills, certifications, projects, publications, personal details) |
| Field extractor | `stages/s4_structure.py` | Regex extraction of email, phone, date fields with word_id/bbox association |
| Date consistency checker | `stages/s4_structure.py` (`_check_dates`) | Future-date and end-before-start heuristics |
| Span/bbox associator | `stages/s4_structure.py` (`_find_word_id`) | Links extracted text back to source word records |

## Implementation status

Completed:
- Section detection via alias dictionary
- Field extraction by regex: email, phone, date
- Date consistency checks: future dates (renamed `date:future`), end-before-start (renamed `date:end_before_start`)
- Word span/bbox association for fields and sections
- Reading-order text input from Stage 2 matched + OCR_ONLY words

Stubbed / not yet wired:
- Full section detection signals (layout, position, content shape) — currently alias matching only
- Conservation ledger (every verified character placed or unplaced)
- Labels CONTRADICTION/CONFLICT/FACT/NOT_EVALUATED with reasons
- Rule families R1-R11, F1-F6, J1-J3
- Manipulation flags M2-M5 (M1 injection flag exists in Stage 2 verdict)
- record_root computation and sealing
- pii_ref for identity separation
- Job-description requirement extraction and DRS

## Files

- `stages/s4_structure.py` — extract_structure, Section, Field dataclasses

## Tests

`tests/test_s4_structure.py`: extract sections and fields — contact and experience sections detected, email field extracted with word_id association.
