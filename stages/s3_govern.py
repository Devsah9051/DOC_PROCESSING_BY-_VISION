from __future__ import annotations

from typing import Optional

from app import db
from app.schemas import Verdict


def latest_version_ok() -> tuple[bool, str]:
    """4.2 Latest-version check (stub interface until spec fields exist)."""
    return True, "stub: latest-version check not yet wired"


def job_open_ok() -> tuple[bool, str]:
    """4.3 Job-open check (stub interface until spec fields exist)."""
    return True, "stub: job-open check not yet wired"


def govern(upload_id: str, sha256: str, verdict: Verdict, quarantine_payload: Optional[str] = None) -> tuple:
    """4.1 + 4.4 Write audit log once per upload_id; QUARANTINED => stop.
    Returns (proceed: bool, reason: str)."""
    rules = list(verdict.rules)
    db.audit_insert(upload_id, sha256, verdict.status, rules, quarantine_payload)

    if verdict.status == "QUARANTINED":
        return False, "quarantined: stages 4-5 skipped"

    ok_v, reason_v = latest_version_ok()
    if not ok_v:
        return False, reason_v
    ok_j, reason_j = job_open_ok()
    if not ok_j:
        return False, reason_j
    return True, "governance passed"
