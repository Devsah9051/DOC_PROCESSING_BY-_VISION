# Stage 4: Structure

Document structure detection from clean text.

## Responsibilities
- Detect document sections from alias list
- Extract fields via regex: email, phone, date
- Associate fields with word_ids and bounding boxes
- Run date consistency checks

## Entry Point
`extract_structure(clean_text, word_records)` → `(List[Section], List[Field])`

## Section Aliases
summary, professional summary, objective, experience, work experience, employment,
professional experience, education, skills, technical skills, certifications,
projects, publications, contact, personal details

## Spec Coverage
See `checkpoints/stage4_structure.md` for full spec gap analysis.
