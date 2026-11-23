from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel

Status = Literal["CLEAN", "SUSPICIOUS", "QUARANTINED"]


class WordRecord(BaseModel):
    word_id: str
    page: int
    bbox: List[float]
    text: str
    source: str
    visible: bool
    flags: List[str] = []


class Flag(BaseModel):
    rule_id: str
    evidence: str
    severity: str


class PageReport(BaseModel):
    page: int
    has_text_layer: bool
    needs_ocr: bool
    words: List[WordRecord] = []
    flags: List[Flag] = []
    ocr_used: bool = False


class Verdict(BaseModel):
    status: Status
    score: float
    rules: List[str] = []
    reasons: List[str] = []


class Phase1Output(BaseModel):
    sections: List[dict] = []
    tokens: List[WordRecord] = []
    verdict: Verdict
    versions: dict
    timings_ms: dict
    prev_hash: str
    report_hash: str
    signature: str


class IntakeResult(BaseModel):
    sha256: str
    size_bytes: int
    page_count: int
    encrypted: bool
    cache_hit: bool
