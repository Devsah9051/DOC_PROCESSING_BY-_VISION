from __future__ import annotations

from typing import Optional

from app import db
from app.config import config
from app.hash import idem_hash, state_hash
from app.log import append_log
from app.schemas import (
    Verdict, FileState, Finding,
)

# --- Section 7.4: Suspicion rating weights ---
# Weights keyed by severity (policy values).
# One High finding alone → quarantine threshold; one Medium alone → review threshold.
# Thresholds come from config (config.yaml); defaults match previous constants.
SEVERITY_WEIGHTS = {
    "High": 5.0,
    "Medium": 2.0,
    "Low": 1.0,
    "Informational": 0.0,
}

# Read from config; fall back to previous effective values if not set
REVIEW_THRESHOLD = config.review_threshold   # one Medium finding alone reaches review
QUARANTINE_THRESHOLD = config.quarantine_threshold  # one High finding alone reaches quarantine


def _severity_to_weight(severity: str) -> float:
    return float(SEVERITY_WEIGHTS.get(severity, 1.0))


def compute_suspicion(findings: list[Finding]) -> tuple[float, str, list[str]]:
    """Compute suspicion total from findings (Section 7.4).

    Returns (total, tier, rule_ids).
    One finding = one region per type, capped per type.
    Informational flags weigh 0.
    """
    total = 0.0
    rule_ids: list[str] = []
    # Cap per finding type to prevent a large harmless block from reaching QUARANTINE alone
    type_caps: dict[str, int] = {}
    for f in findings:
        if f.severity in ("Informational",):
            continue  # weigh 0
        w = _severity_to_weight(f.severity)
        total += w
        rule_ids.append(f.rule_id)

    if total >= QUARANTINE_THRESHOLD:
        tier = "QUARANTINE"
    elif total >= REVIEW_THRESHOLD:
        tier = "REVIEW"
    else:
        tier = "CLEAN"
    return total, tier, rule_ids


def govern_pre(upload_id: str, sha256: str, config, scan_findings: list | None = None) -> dict:
    """Stage 3 pre-gate (Section 7.2).

    Runs before any parsing. Decides whether this version should continue.
    Returns {"proceed": bool, "reason": str}.
    """
    import time

    t0 = time.time()

    # Idempotency key (Section 7.2, 4.1): SHA-256(egca/idem/v1 + 0x00 + version_id + ":" + parser_build_id)
    parser_build_id = config.pipeline_version
    idem_key = idem_hash(upload_id, parser_build_id)

    # Check idempotency / result cache
    cached = db.cache_get(sha256, config.pipeline_version, config.rules_version)
    if cached is not None:
        append_log("GATE_DECISION", {
            "upload_id": upload_id,
            "sha256": sha256,
            "decision": "CACHE_HIT",
            "idem_key": idem_key,
        })
        return {"proceed": False, "reason": "cached_result_reused"}

    # Consider Stage 1 scan findings (synchronous scan + CDR already applied)
    # High-severity findings already blocked at Stage 1 (BLOCKED → QUARANTINE).
    # Medium-severity findings → REVIEW tier.
    review_findings = []
    if scan_findings:
        for f in scan_findings:
            if f.get("severity") == "Medium":
                review_findings.append(f)
    if review_findings:
        append_log("GATE_DECISION", {
            "upload_id": upload_id,
            "sha256": sha256,
            "decision": "PRE_GATE_REVIEW",
            "review_findings": [f["rule_id"] for f in review_findings],
            "idem_key": idem_key,
        })
        return {"proceed": True, "reason": "pre_gate_review", "review_findings": review_findings}

    # Epoch fencing / state watcher (stubs - wire to external services per spec)
    # version_seq fencing: if newer version accepted, older → SUPERSEDED
    # state watcher: JOB_CLOSED / APPLICATION_WITHDRAWN → ARCHIVED_INACTIVE

    append_log("GATE_DECISION", {
        "upload_id": upload_id,
        "sha256": sha256,
        "decision": "PRE_GATE_PASS",
        "idem_key": idem_key,
        "elapsed_ms": round((time.time() - t0) * 1000, 2),
    })
    return {"proceed": True, "reason": "pre_gate_passed"}


def govern_post(
    upload_id: str,
    sha256: str,
    verdict: Verdict,
    quarantine_payload: Optional[str] = None,
    scan_findings: list | None = None,
    cdr_applied: bool = False,
) -> dict:
    """Stage 3 post-gate (Section 7.2).

    Runs after Stage 2. Universal injection scan, suspicion rating, file state.
    Returns {"proceed": bool, "reason": str, "file_state": FileState | None}.
    """
    import time

    t0 = time.time()

    # Universal injection scan (Section 7.3) - already run in Stage 2 via flags;
    # here we consolidate findings into the file state.

    # Build findings from verdict rules + flags
    findings: list[Finding] = []
    for rule_id in verdict.rules:
        sev = "High" if rule_id == "INJECTION_STRONG" else "Medium"
        findings.append(Finding(rule_id=rule_id, evidence=verdict.reasons[0] if verdict.reasons else "", severity=sev))

    # Incorporate Stage 1 scan findings (YARA, CDR, etc.) into suspicion rating
    if scan_findings:
        for f in scan_findings:
            sev = f.get("severity", "Medium")
            findings.append(Finding(
                rule_id=f.get("rule_id", "SCAN_FINDING"),
                evidence=f.get("description", ""),
                severity=sev,
            ))

    # CDR applied means Stage 1 found medium-severity issues that required sanitization
    if cdr_applied:
        findings.append(Finding(
            rule_id="CDR_APPLIED",
            evidence="Stage 1 applied CDR sanitization due to YARA findings",
            severity="Medium",
        ))

    # Suspicion rating (Section 7.4)
    total, tier, rule_ids = compute_suspicion(findings)

    # Parse status from verdict (Stage 2 sets parse status)
    parse_status = "PARSED"
    if verdict.status == "QUARANTINE":
        parse_status = "PARSE_FAILED"

    # Build file state (Section 4.2)
    file_state = FileState(
        risk_tier=tier,
        suspicion_status=verdict.status,
        parse_status=parse_status,
        findings=findings,
        warnings=list(verdict.reasons),
    )

    fs_hash = state_hash(file_state.model_dump())

    # Early stop: QUARANTINE does not go to Stage 4 (Section 7.2)
    proceed = tier != "QUARANTINE"
    reason = "post_gate_passed" if proceed else f"quarantined: total={total:.1f} >= {QUARANTINE_THRESHOLD}"

    # Audit log entry (GATE_DECISION)
    append_log("GATE_DECISION", {
        "upload_id": upload_id,
        "sha256": sha256,
        "decision": tier,
        "total": total,
        "rule_ids": rule_ids,
        "file_state_hash": fs_hash,
        "elapsed_ms": round((time.time() - t0) * 1000, 2),
    })

    # Also write to governance_audit_log for backward compatibility
    try:
        db.audit_insert(upload_id, sha256, tier, rule_ids, quarantine_payload)
    except Exception:
        pass

    return {"proceed": proceed, "reason": reason, "file_state": file_state}
