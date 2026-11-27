# Stage 3: Govern

Pre-gate and post-gate governance decisions.

## Responsibilities
- Pre-gate: idempotency key, epoch fencing, state watcher, cache check
- Post-gate: universal injection scan, suspicion rating, file state
- Suspicion rating: weighted sum of finding severities
- Final risk tier: CLEAN / REVIEW / QUARANTINE

## Entry Points
- `govern_pre(upload_id, sha256, config)` → dict
- `govern_post(upload_id, sha256, verdict, quarantine_payload)` → dict

## Spec Coverage
See `checkpoints/stage3_govern.md` for full spec gap analysis.

## Known Stubs
- `latest_version_ok()` — not wired to external service
- `job_open_ok()` — not wired to external service
