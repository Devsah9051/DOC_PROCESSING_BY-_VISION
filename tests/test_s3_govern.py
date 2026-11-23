from __future__ import annotations

from app.schemas import Verdict
from stages.s3_govern import govern, latest_version_ok, job_open_ok


def test_govern_clean_proceeds():
    v = Verdict(status="CLEAN", score=1.0, rules=[], reasons=[])
    proceed, reason = govern("u1", "sha", v)
    assert proceed is True


def test_govern_quarantined_stops():
    v = Verdict(status="QUARANTINED", score=10.0, rules=["INJECTION_STRONG"], reasons=["inj"])
    proceed, reason = govern("u1", "sha", v)
    assert proceed is False
    assert "quarantined" in reason


def test_stubs_return_true():
    assert latest_version_ok()[0] is True
    assert job_open_ok()[0] is True
