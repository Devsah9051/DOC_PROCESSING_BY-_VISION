# README — Stage 3: Govern (Ingestion and Governance)

Source specification: EGCA Phase 1 Final Specification rev4, Section 7 ("Stage 3: Ingestion and governance") and Section 4.3 (signed seal and append-only log).

## Purpose

Stage 3 is the rule-keeper and guard. It checks twice whether a version should continue: before any heavy parsing (pre-gate) and after parsing (post-gate). At the post-gate it scans every file for instructions, sets the final risk tier, handles warnings and near-duplicates, and writes every decision to the append-only log.

## Steps

### Pre-gate (right after Stage 1, before parsing; uses only what Stage 1 knows)

1. **Idempotency** — key = SHA-256 of `egca/idem/v1`, `0x00`, `version_id`, colon, `parser_build_id`. Same version parsed by same build accepted once; repeat returns earlier result.
2. **Epoch fencing** — each accepted version carries `version_seq`. If a newer version accepted, older one marked SUPERSEDED and stops.
3. **State watcher** — events such as JOB_CLOSED or APPLICATION_WITHDRAWN move waiting items to ARCHIVED_INACTIVE and stop further work. Runs again at post-gate.
4. **Result cache** — if same `original_sha256` already processed under same versions, stored result reused instead of parsing again. New version still registered and logged.

### Post-gate (after Stage 2; uses parse results)

1. **State watcher again** — if job closed or application withdrawn while Stage 2 ran, file stops here.
2. **Universal injection scan** — every file with text scanned for instructions (spec 7.3).
3. **Suspicion rating** — findings added up, final risk tier set (spec 7.4).
4. **Early stop** — PARTIAL, PARSE_FAILED, QUARANTINE and blocking warnings do not go to Stage 4.
5. **Warning policy** — warnings handled by severity and track.
6. **Near-duplicate check** — within one slot, very similar new version flagged NEAR_DUPLICATE for reviewer; not auto-merged.
7. **Audit** — every decision at both gates appended to append-only log (entry kind GATE_DECISION), written with outgoing message via transactional outbox.

## Suspicion rating and final risk tier (7.4)

Each finding carries a weight set by severity. Cumulative total:
- Below review threshold: CLEAN
- At or above review threshold: REVIEW with status SUSPECT
- At or above quarantine threshold: QUARANTINE

One High finding alone reaches quarantine threshold; one Medium alone reaches review threshold; several Medium together can reach quarantine. Flags M2 to M5 (raised in Stage 4) can lift CLEAN to REVIEW but never to QUARANTINE.

Risk tier: CLEAN, REVIEW, QUARANTINE. Parse status: PARSED, PARSED_WITH_WARNINGS, PARTIAL, PARSE_FAILED.

## Universal injection scan (7.3)

Runs on every file reaching post-gate with text, whatever Stage 2 found. Reads visible text (verified blocks) and hidden text (dropped words from forensic_ref, side channel such as annotations/metadata). Side channel read by scanner only, never mixed into text. Hits record rule id, place (block id and span or word reference in forensic bundle), severity. Hits in visible blocks become M1 INSTRUCTION_LIKE flags handed to Stage 4. Flagged text never turned into skill claim; tagger never runs on it.

## File state (4.2)

Risk tier, suspicion status, parse status, hidden-content findings and warnings hashed once at post-gate as `file_state_hash` and signed with `stage5_root`, so it cannot be edited unseen.

## Append-only log (4.3)

Every seal appended to append-only log. Each log entry includes previous entry's hash. Entry kinds: GATE_DECISION, SEAL, FILE_STATE_UPDATE, HUMAN_DECISION, TOMBSTONE, CHECKPOINT. One log only. All appends go through one function with database lock. Periodic checkpoint (latest hash, signed) exported outside system.

## Functional Components

| Component | File | Responsibility |
|---|---|---|
| Gate auditor | `stages/s3_govern.py` (`govern`) | Writes audit log per upload_id; QUARANTINED stops stages 4-5 |
| Latest-version checker | `stages/s3_govern.py` (`latest_version_ok`) | Stub — returns True, not wired to external services |
| Job-open checker | `stages/s3_govern.py` (`job_open_ok`) | Stub — returns True, not wired to external services |
| Audit logger | `app/db.py` (`audit_insert`) | Persists upload status, rules, quarantine payload (stubbed in tests) |
| Result cache | `app/db.py` (`cache_get`/`cache_insert`) | Partially wired in Stage 1 only; per-stage keys not yet implemented |

## Implementation status

Completed:
- `govern()` function: audit log insert per upload_id, QUARANTINED stop (stages 4-5 skipped)
- Stub: `latest_version_ok()` — returns True, not yet wired to external services
- Stub: `job_open_ok()` — returns True, not yet wired to external services
- DB `audit_insert()` query (stubbed in tests without live PostgreSQL)

Stubbed / not yet wired:
- Idempotency key computation and check
- Epoch fencing / version_seq
- State watcher (JOB_CLOSED, APPLICATION_WITHDRAWN)
- Result cache lookup and reuse
- Near-duplicate check
- Transactional outbox for gate decisions
- Suspicion rating with severity weights and thresholds
- Universal scan as separate post-gate step (injection scan currently runs in Stage 2)
- file_state_hash computation and sealing
- Append-only log with entry kinds and checkpoints

## Files

- `stages/s3_govern.py` — govern, latest_version_ok, job_open_ok
- `app/db.py` — audit_insert, cache_get, cache_insert

## Tests

`tests/test_s3_govern.py`: govern clean proceeds, govern quarantined stops, stubs return true.
