from __future__ import annotations

from typing import Dict, List, Literal, Optional
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
    # Optional typography data (Stage 4 support — additive, defaults None)
    size: Optional[float] = None
    bold: Optional[bool] = None
    color: Optional[int] = None
    font: Optional[str] = None

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
    heading_line_id: Optional[str] = None  # line id of the section heading
    line_class: Optional[str] = None       # "HEADING" | "BODY" | "LIST_ITEM" | "PAGE_FURNITURE"


class Field(BaseModel):
    name: str
    value: str
    word_ids: List[str] = []
    bbox: List[float] = []


# ---- Stage 4: Line-level structure (Section 8) ----


class Line(BaseModel):
    """Line-level structure extracted from word records (Section 8)."""
    text: str
    bbox: List[float] = []
    size_max: Optional[float] = None
    size_median: Optional[float] = None
    bold_ratio: Optional[float] = None
    caps_ratio: Optional[float] = None
    x0: Optional[float] = None
    gap_before: Optional[float] = None
    page: int = 1
    line_class: str = "BODY"  # HEADING | BODY | LIST_ITEM | PAGE_FURNITURE


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
    # Stage 2 hash chain (Section 4.2)
    clean_artifact_sha256: Optional[str] = None
    # Seal attestation: original and sanitized bytes (Stream A)
    raw_sha256: Optional[str] = None
    sanitized_sha256: Optional[str] = None
    # Stage 4 structure output (Section 8.8)
    structure_record_root: Optional[str] = None
    structure_pii_ref: Optional[str] = None
    structure_labels: List[Dict[str, str]] = []
    structure_rule_flags: List[str] = []
    structure_manipulation_flags: List[ManipulationFlag] = []
    structure_date_intervals: List[DateInterval] = []
    structure_conservation_ledger: List[Dict] = []
    structure_track: Optional[str] = None


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


class ScanResult(BaseModel):
    """Malware scan result (Section 5.2, scanner daemon)."""
    sha256: str
    file_type: str
    scan_engine: str
    infected: bool
    threat_name: Optional[str] = None
    scanned_at: Optional[str] = None
    payload: Optional[dict] = None


class ScanFinding(BaseModel):
    """A single threat finding from any scanner stage."""
    rule_id: str
    stage: str  # "magic", "zip", "yara", "cdr", "structural", "encryption"
    scan_layer: str  # "raw"|"yara"|"structural"|"cdr"|"encryption"|"zip"
    severity: str  # "High", "Medium", "Low", "Informational"
    description: str
    matched_strings: list[str] = []


class SanitizedArtifact(BaseModel):
    """Output of the CDR pipeline — safe for OCR/LLM consumption (Section 5.2)."""
    sha256: str
    raw_sha256: str  # SHA-256 of original upload (immutable, for audit/forensics)
    file_type: str  # "pdf", "docx", "text"
    original_size: int
    sanitized_size: int
    scan_engine: str
    infected: bool
    threat_name: Optional[str] = None
    findings: list[ScanFinding] = []
    cdr_applied: bool = False
    cdr_method: Optional[str] = None
    sanitized_artifact_uri: Optional[str] = None  # derived artifact storage URI
    sanitized_bytes: Optional[bytes] = None  # raw sanitized bytes for downstream processing
    scanned_at: float = 0.0


# ---- Stage 4: Structure models (Section 8) ----


class DateInterval(BaseModel):
    """A date range with start/end and optional 'Present' marker (Section 8.3)."""
    start: Optional[str] = None  # ISO date string
    end: Optional[str] = None
    is_present: bool = False
    raw_text: str = ""
    word_ids: List[str] = []
    bbox: List[float] = []


class ManipulationFlag(BaseModel):
    """M1-M5 manipulation flag with evidence (Section 8.5)."""
    flag_id: str
    rule_id: str
    evidence: str
    severity: str  # High / Medium / Low
    bbox: List[float] = []
    word_ids: List[str] = []


class StructureResult(BaseModel):
    """Complete Stage 4 output (Section 8.8)."""
    sections: List[Section] = []
    fields: List[Field] = []
    date_intervals: List[DateInterval] = []
    labels: List[Dict[str, str]] = []
    rule_flags: List[str] = []
    manipulation_flags: List[ManipulationFlag] = []
    conservation_ledger: List[Dict] = []
    record_root: str = ""
    pii_ref: str = ""
    track: str = "resume"
    lines: List[Line] = []  # line-level structure (Section 8.8)


# Rule family constants (Section 8.4)
RULE_R1 = "R1_MISSING_REQUIRED_SECTION"
RULE_R2 = "R2_DUPLICATE_SECTION"
RULE_R3 = "R3_EMPTY_SECTION"
RULE_R4 = "R4_OUT_OF_ORDER_SECTIONS"
RULE_R5 = "R5_UNKNOWN_SECTION"
RULE_R6 = "R6_INVALID_EMAIL_FORMAT"
RULE_R7 = "R7_INVALID_PHONE_FORMAT"
RULE_R8 = "R8_DATE_IN_FUTURE"
RULE_R9 = "R9_END_BEFORE_START"
RULE_R10 = "R10_GAP_IN_EMPLOYMENT"
RULE_R11 = "R11_INCONSISTENT_DATE_FORMAT"

RULE_F1 = "F1_MIXED_DATE_FORMATS"
RULE_F2 = "F2_INCONSISTENT_FONT_SIZES"
RULE_F3 = "F3_OVERLAPPING_TEXT_BLOCKS"
RULE_F4 = "F4_TEXT_OUTSIDE_MARGINS"
RULE_F5 = "F5_UNUSUAL_CHARACTER_SPACING"
RULE_F6 = "F6_WATERMARK_OR_BACKGROUND"

RULE_J1 = "J1_MISSING_REQUIREMENTS_SECTION"
RULE_J2 = "J2_MISSING_RESPONSIBILITIES"
RULE_J3 = "J3_VAGUE_QUALIFICATIONS"

FLAG_M1 = "M1_HIDDEN_TEXT"
FLAG_M2 = "M2_REMAPPED_GLYPH"
FLAG_M3 = "M3_OVERLAPPING_BBOX"
FLAG_M4 = "M4_TEXT_OUTSIDE_VISIBLE"
FLAG_M5 = "M5_ANOMALOUS_FONT_MAP"

LABEL_CONTRADICTION = "CONTRADICTION"
LABEL_CONFLICT = "CONFLICT"
LABEL_FACT = "FACT"
LABEL_NOT_EVALUATED = "NOT_EVALUATED"

# Rebuild models with forward references (Phase1Output references StructureResult)
Phase1Output.model_rebuild()
StructureResult.model_rebuild()
