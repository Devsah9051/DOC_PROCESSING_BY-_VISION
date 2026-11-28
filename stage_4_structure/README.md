# Stage 4: Structure

Document structure detection from clean text — section detection, field extraction, date intervals, labels, rule flags, manipulation flags, conservation ledger, and sealed record output.

## Responsibilities
- Detect document sections from alias list (contact, summary, experience, education, skills, certifications, projects, publications, awards, references)
- Extract fields via regex: email, phone, URL, LinkedIn, GitHub, dates
- Associate fields with word_ids and bounding boxes via O(1) WordIndex
- Build date intervals with start/end dates; "Present" → as_of from uploaded_at
- Run date consistency checks (future dates R8, end-before-start R9, inconsistent formats R11)
- Apply rule families R1-R11, F1-F6, J1-J3
- Apply labels: CONTRADICTION, CONFLICT, FACT, NOT_EVALUATED
- Apply manipulation flags M1-M5 from Stage 2 word findings
- Maintain conservation ledger (append-only audit entries)
- Produce sealed output: record_root + pii_ref
- Support job_description track with J1-J3 rules

## Entry Point
`extract_structure(clean_text, word_records, track, uploaded_at)` → `StructureResult`

## Return Type
`StructureResult` containing:
- `sections`: List[Section] — detected sections with text, word_ids, bbox
- `fields`: List[Field] — extracted fields (email, phone, URL, LinkedIn, GitHub, date)
- `date_intervals`: List[DateInterval] — date ranges with start/end/is_present
- `labels`: List[Dict[str, str]] — field → label mapping (CONTRADICTION/CONFLICT/FACT/NOT_EVALUATED)
- `rule_flags`: List[str] — triggered rules (R1-R11, F1-F6, J1-J3)
- `manipulation_flags`: List[ManipulationFlag] — M1-M5 findings with evidence
- `conservation_ledger`: List[Dict] — append-only audit entries
- `record_root`: str — hash of sealed record
- `pii_ref`: str — SHA-256 pointer to PII storage
- `track`: str — "resume" or "job_description"

## Section Aliases
contact, summary, professional summary, profile, objective, career objective,
experience, work experience, employment, professional experience, work history,
education, academic background, qualifications,
skills, technical skills, core competencies, expertise,
certifications, certificates, licenses,
projects, key projects, selected projects,
publications, research publications, papers,
awards, honors, achievements,
references, professional references

## Rule Families
- R1-R11: Resume structure/integrity (missing sections, duplicates, empty sections, out of order, unknown sections, invalid email/phone, future dates, end before start, employment gap, inconsistent formats)
- F1-F6: Formatting/presentation (mixed date formats, inconsistent font sizes, overlapping blocks, text outside margins, unusual spacing, watermark)
- J1-J3: Job description track (missing requirements, missing responsibilities, vague qualifications)

## Manipulation Flags (M1-M5)
- M1_HIDDEN_TEXT — invisible/hidden text
- M2_REMAPPED_GLYPH — custom font mapping hides real text
- M3_OVERLAPPING_BBOX — overlapping bounding boxes
- M4_TEXT_OUTSIDE_VISIBLE — text marked invisible but extracted
- M5_ANOMALOUS_FONT_MAP — font cmap doesn't match extracted glyphs

## Spec Coverage
See `checkpoints/stage4_structure.md` for full spec gap analysis.

## Optimizations
- `WordIndex`: O(1) text→word_id lookup (replaces O(n*m) linear scan)
- `lookup()` (peek) vs `find()` (consume): prevents word double-consumption
- Memoized date parsing: avoids re-parsing duplicate date strings
