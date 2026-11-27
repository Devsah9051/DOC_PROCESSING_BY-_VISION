from __future__ import annotations

from app.schemas import Verdict
from stages.s3_govern import govern_pre, govern_post


def test_govern_pre_clean_proceeds():
    result = govern_pre("u1", "sha", type("Config", (), {"pipeline_version": "1.0.0", "rules_version": "1.0.0", "weights": {}})())
    assert result["proceed"] is True


def test_govern_post_clean_proceeds():
    v = Verdict(status="CLEAN", score=1.0, rules=[], reasons=[])
    result = govern_post("u1", "sha", v)
    assert result["proceed"] is True


def test_govern_post_quarantine_stops():
    v = Verdict(status="QUARANTINE", score=10.0, rules=["INJECTION_STRONG"], reasons=["inj"])
    result = govern_post("u1", "sha", v)
    assert result["proceed"] is False
    assert "quarantined" in result["reason"]
