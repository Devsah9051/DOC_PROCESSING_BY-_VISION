# README — Stage 1: Upload and Intake

Source specification: EGCA Phase 1 Final Specification rev4, Section 5 ("Stage 1: Upload and quarantine") and Section 4.1 (hashing rules).

## Purpose

Stage 1 is the front door of the pipeline. A resume or job description file arrives as raw bytes and is checked for basic safety and integrity before anything is read or understood. It is fingerprinted, registered as a version, and either cleared for the Stage 3 pre-gate or routed to a terminal outcome. Nothing is parsed yet.

## What it does

1. **Receive into quarantine** — raw bytes are held in write-once storage that no other stage can modify.
2. **Check the file** — real type comes from the first bytes (`%PDF-` for PDF, `PK` for DOCX, valid text for plain text), never from the file name. Size and page limits, encryption, archive bombs, and active content are checked.
3. **Fingerprint** — compute `original_sha256` over the exact bytes. This is the root of every trace and the key of the result cache.
4. **Register the version** — a version registry keyed by owner, job and track assigns a `version_id` and `version_seq`. Registration uses compare-and-swap so two simultaneous uploads cannot both become the latest.
5. **Decide the outcome and announce it** — outcome and job message are written in one database transaction (transactional outbox).

## Outcomes

| Outcome | Meaning | What happens next |
|---|---|---|
| READY | Passed every check | Sent to Stage 3 pre-gate, then Stage 2 |
| DUPLICATE | Same `original_sha256` already registered for this owner/job | Linked to existing version; no new work |
| REJECTED | Wrong type, over limit, or encrypted without a way to open it | Candidate told why; stops |
| BLOCKED | Malware or active-content risk | Held for security review; never parsed |
| FAILED | Temporary fault (storage, scanner) | Retried with limits, then escalated |
| EXPIRED | Upload window or retention period passed | Archived, or deleted with a signed tombstone |

## Hashing rules (from spec 4.1)

- Canonical form: JSON keys sorted, UTF-8, no extra whitespace, Unicode NFC text, positions stored as integers.
- `original_sha256` is the plain SHA-256 of the file bytes (recomputable with standard tools).
- Domain-tagged hashes use `SHA-256(tag + 0x00 + canonical bytes)` per record type.

## Functional Components

| Component | File | Responsibility |
|---|---|---|
| Intake validator | `stages/s1_intake.py` | Size cap, safe filename, PDF header check, encrypted/oversized page rejection |
| Fingerprinter | `stages/s1_intake.py` | Computes `original_sha256` over raw bytes |
| Version registrar | `stages/s1_intake.py` (stubbed) | Assigns `version_id`/`version_seq` via compare-and-swap (not yet wired) |
| Result cache lookup | `app/db.py` (`cache_get`) | Reuses stored output when `sha256` + pipeline version + rules version match |
| Config provider | `app/config.py` (`Config`) | Loads `dpi`, `max_bytes`, `max_pages`, `max_pixels`, contrast and other limits |
| Outcome announcer | `app/pipeline.py` | Writes outcome + job message in transactional outbox (not yet wired) |

## Implementation status

Completed:
- File size cap enforcement (`max_bytes`)
- Safe filename validation
- PDF header (`%PDF-`) validation
- SHA-256 fingerprint computation
- Encrypted PDF rejection
- Page count limit (`max_pages`)
- Max pixels per page limit (`max_pixels`)
- Result cache lookup keyed by `sha256` + pipeline version + rules version
- `original_sha256` computed and carried through the pipeline as `prev_hash`

Stubbed / not yet wired:
- DOCX and plain-text routes (spec 6.12)
- Malware scan via scanner daemon (optional in v1)
- Version registry with compare-and-swap registration
- Transactional outbox for outcome announcement
- Write-once quarantine storage

## Files

- `stages/s1_intake.py` — intake logic
- `app/config.py` — configuration (dpi, max_bytes, max_pages, max_pixels, contrast_min, etc.)
- `config/config.yaml` — configuration values

## Tests

`tests/test_pipeline.py`: corrupt PDF, oversized PDF, injection (visible + metadata), tiny font, off-page, zero-width, white-on-white, covered text — all routed to QUARANTINED or flagged as expected.
