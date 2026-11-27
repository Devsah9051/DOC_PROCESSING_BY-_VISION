from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel

# --- Status / Risk Tier (Section 7.4) ---
# Spec uses CLEAN, REVIEW (with SUSPECT status), QUARANTINE.
Status = Literal["CLEAN", "REVIEW", "QUARANTINE"]
VerdictStatus = Literal["CLEAN", "REVIEW", "QUARANTINE", "FAILED"]


class WordRecord(BaseModel):
    word_id: str
    page: int
    bbox: List[float]
    text: str
    source: str
    visible: bool
    flags: List[str] = []

    def __getitem__(self, key: str):
        return getattr(self, key)


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


class Finding(BaseModel):
    """One hidden-content or manipulation finding (Section 6.8, 7.4, 8.5)."""
    rule_id: str
    evidence: str
    severity: Literal["High", "Medium", "Low", "Informational"]
    page: Optional[int] = None
    bbox: Optional[List[float]] = None


class Verdict(BaseModel):
    status: VerdictStatus
    score: float
    rules: List[str] = []
    reasons: List[str] = []
    findings: List[Finding] = []


class FileState(BaseModel):
    """File state hashed and sealed at Stage 3 post-gate (Section 4.2)."""
    risk_tier: Literal["CLEAN", "REVIEW", "QUARANTINE"]
    suspicion_status: Optional[str] = None
    parse_status: Optional[str] = None
    findings: List[Finding] = []
    warnings: List[str] = []


class Section(BaseModel):
    name: str
    text: str
    word_ids: List[str] = []
    bbox: List[float] = []
    start_line: int = 0
    end_line: int = 0


class Field(BaseModel):
    name: str
    value: str
    word_ids: List[str] = []
    bbox: List[float] = []


class Phase1Output(BaseModel):
    sections: List[Section] = []
    tokens: List[WordRecord] = []
    verdict: Verdict
    file_state: Optional[FileState] = None
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


class BlockRecord(BaseModel):
    """Stage 2 output block (Section 6.10)."""
    block_id: str
    block_hash: str
    page: int
    frame_id: Optional[str] = None
    bbox: List[float] = []
    column_id: Optional[str] = None
    reading_order: int = 0
    verdict: str  # CORROBORATED, CORROBORATED_FUZZY, UNCORROBORATED_NOT_VISIBLE, UNCORROBORATED_TEXT_MISMATCH, ICON_GLYPH, OCR_ONLY, TEXT_SOURCE


class IntakeOutcome(BaseModel):
    """Stage 1 outcome (Section 5.3)."""
    outcome: Literal["READY", "DUPLICATE", "REJECTED", "BLOCKED", "FAILED", "EXPIRED"]
    version_id: str
    version_seq: int
    original_sha256: str
    file_type: str
    size_bytes: int
    uploaded_at: float
    track: Literal["resume", "job_description"]
    quarantine_pointer: Optional[str] = None
