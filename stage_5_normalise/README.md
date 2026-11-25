# README — Stage 5: Normalise

Source specification: EGCA Phase 1 Final Specification rev4, Section 9 ("Stage 5: Normalisation"), Section 9.7 (taxonomy source and maintenance), Section 9.3 (skill relations).

## Purpose

Stage 5 maps each skill, title and number to one standard name from a versioned list, so later stages compare like with like. It never guesses: if two names are not known to be the same, they stay different (Java is not JavaScript). Counts each skill once, describes how skills relate (without scores), and seals the result as `stage5_root`.

## Modules

| Module | What it does |
|---|---|
| Intake verifier | Re-checks record_root and hash chain before touching anything |
| Term normaliser | Exact match first, then alias match. Only an alias_of entry makes two names equal. Negative-pair file keeps lookalikes apart (Java/JavaScript, C/C#) |
| Value normaliser | Standard units for durations, degrees, grades; ranges kept as ranges |
| Provenance tag | STATED (as written), NORMALIZED (mapped by alias), PROPOSED_AGREED (tagger proposal accepted through gate), INFERRED (reserved; empty in v1) |
| Status | PRESENT, UNMAPPED (not in the list), NOT_ACCEPTED (flagged text), MISSING |
| Aggregator | Counts each canonical skill once, however many times it appears; self-rated levels pass through as stated, not trusted |
| Packer and sealer | Writes normalised record and stage5_root |

## Skill relations (9.3)

Versioned relation table records, per taxonomy version, each skill's kind, family and ecosystem. Relation classes:
- SAME_FAMILY_SAME_ECOSYSTEM
- SAME_ECOSYSTEM_DIFFERENT_FAMILY
- SAME_FAMILY_DIFFERENT_ECOSYSTEM
- PREREQUISITE

No scores. A relation never satisfies a mandatory requirement; only alternatives approved by recruiter can. Records carry families[] and ecosystems[].

## Invariants (9.4)

- Flagged text (M1 to M5) passes through as flagged and is never turned into a normalised skill.
- Nothing merged without an alias entry. Fuzzy matcher may only suggest aliases to maintainer queue. Build fails if alias maps to two ids or if a negative pair shares an id.
- Taxonomy version recorded in every output.
- If taxonomy changes, re-run produces new stage5_root; old one stays valid for its version.

## Job-description track (9.6)

Job requirements pass through same normaliser. Output is draft requirement set where each item shows canonical id, family, ecosystem and taxonomy's related skills, presented to recruiter. Relation is only a suggestion; becomes approved alternative only when recruiter approves, then part of sealed DRS.

## Taxonomy source and maintenance (9.7)

Taxonomy (canonical skills, aliases, negative pairs, relation table) starts from public bases such as ESCO and O*NET, trimmed to target fields (software roles first) and extended by hand. Every change made by named taxonomy maintainer through decision service as signed entry with reason, creates new immutable taxonomy version, tested on labelled skill list before release. A term not in taxonomy is never merged; recorded as UNMAPPED and counted. Literal key for each UNMAPPED term (term after case and spacing folding only).

## Functional Components

| Component | File | Responsibility |
|---|---|---|
| Taxonomy loader | `stages/s5_normalise.py` (`load_taxonomy`) | Loads skill taxonomy from `config/taxonomy.yaml` (canonical skills, aliases, related) |
| Term normaliser | `stages/s5_normalise.py` (`_canonicalize`) | Exact match, alias match, then fuzzy match (rapidfuzz >= 85) |
| Skill aggregator | `stages/s5_normalise.py` (`normalise_tokens`) | Deduplicates canonical skills, aggregates word_ids, carries related skills |
| Output builder & sealer | `stages/s5_normalise.py` (`build_output`) | Canonical hash (report_hash) + Ed25519 seal (signature) |
| Cache writer | `stages/s5_normalise.py` (`write_cache`) | Writes output to result cache via `cache_insert` |

## Implementation status

Completed:
- Taxonomy loading from YAML
- Skill normalisation: exact match (case-insensitive), then alias match, then fuzzy match (rapidfuzz >= 85)
- Negative-pair concept (taxonomy has no negative pairs yet; structure supports aliases)
- Deduplication: each canonical skill counted once, word_ids aggregated
- Related skills from taxonomy carried through
- Provenance/status concepts (STATED, UNMAPPED) — implemented implicitly
- Output building with canonical hash (report_hash) and Ed25519 seal (signature)
- Result cache write (cache_insert)
- Deterministic output: same input + versions = same report_hash and signature

Stubbed / not yet wired:
- Value normaliser (standard units for durations, degrees, grades)
- Negative-pair file (Java/JavaScript, C/C# kept apart)
- Provenance tag PROPOSED_AGREED / INFERRED
- Status PRESENT / MISSING / NOT_ACCEPTED tracking
- Aggregator with counts
- Skill relations table (family, ecosystem, relation classes)
- record_root intake verification
- stage5_root computation (currently uses report_hash as output hash)
- Taxonomy maintenance via decision service with signed entries
- Literal key for UNMAPPED terms
- Job-description requirement normalisation and DRS

## Files

- `stages/s5_normalise.py` — load_taxonomy, normalise_tokens, build_output, write_cache
- `config/taxonomy.yaml` — skill taxonomy (python, java, javascript, typescript, sql, aws, docker, kubernetes, machine_learning, project_management)

## Tests

`tests/test_s5_normalise.py`: normalise canonical skills (python, js dedup), unknown skill kept, build output hash and seal deterministic.
