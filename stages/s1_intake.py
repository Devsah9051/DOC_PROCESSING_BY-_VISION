from __future__ import annotations

import hashlib
import io
import os
import re
import time
import zipfile
from dataclasses import dataclass, field
from typing import Optional

import pymupdf

from app.config import config
from app.db import cache_get, get_version, register_version
from app.scanner import scan_file, SanitizedArtifact, ScanFinding

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
PDF_HEADER = b"%PDF-"
DOCX_HEADER = b"PK\x03\x04"

VALID_OUTCOMES = ("READY", "DUPLICATE", "REJECTED", "BLOCKED", "FAILED", "EXPIRED")


class Stage1Error(Exception):
    """Fatal intake failure (programming error / unexpected)."""


@dataclass
class IntakeContext:
    outcome: str
    sha256: str
    size_bytes: int
    filename: str
    file_type: str
    track: str
    version_id: str
    version_seq: int
    uploaded_at: float
    quarantine_pointer: Optional[str] = None
    page_count: int = 0
    encrypted: bool = False
    cache_hit: bool = False
    cached_output: Optional[dict] = None
    doc: object | None = None
    reason: str = ""
    # Scanner output (Stage 5.2 — synchronous scan + CDR)
    sanitized_artifact: Optional[SanitizedArtifact] = None
    scan_findings: list[ScanFinding] = field(default_factory=list)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def detect_file_type(file_bytes: bytes) -> str:
    if file_bytes.startswith(PDF_HEADER):
        return "pdf"
    if file_bytes.startswith(DOCX_HEADER):
        return "docx"
    try:
        file_bytes.decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        return "unknown"


def is_safe_filename(filename: str) -> bool:
    name = os.path.basename(filename)
    if not name or name in (".", ".."):
        return False
    return SAFE_NAME_RE.match(name) is not None


def detect_track(filename: str) -> str:
    name = filename.lower()
    if any(k in name for k in ("jd", "job", "description", "position", "role", "vacancy")):
        return "job_description"
    return "resume"


def _build_version_id(sha256: str, seq: int) -> str:
    return f"{sha256[:16]}:v{seq}"


def intake(file_bytes: bytes, filename: str, upload_id: str, cfg=config) -> IntakeContext:
    sha = sha256_of(file_bytes)
    size_bytes = len(file_bytes)
    file_type = detect_file_type(file_bytes)
    track = detect_track(filename)
    uploaded_at = time.time()

    # 2.1 safe filename
    if not is_safe_filename(filename):
        return IntakeContext(
            outcome="REJECTED", sha256=sha, size_bytes=size_bytes, filename=filename,
            file_type=file_type, track=track,
            version_id="", version_seq=0, uploaded_at=uploaded_at,
            reason="unsafe_filename",
        )

    # 2.1 size cap
    if size_bytes > cfg.max_bytes:
        return IntakeContext(
            outcome="REJECTED", sha256=sha, size_bytes=size_bytes, filename=filename,
            file_type=file_type, track=track,
            version_id="", version_seq=0, uploaded_at=uploaded_at,
            reason="file_exceeds_max_bytes",
        )

    # 2.1 file type
    if file_type == "unknown":
        return IntakeContext(
            outcome="REJECTED", sha256=sha, size_bytes=size_bytes, filename=filename,
            file_type=file_type, track=track,
            version_id="", version_seq=0, uploaded_at=uploaded_at,
            reason="unsupported_file_type",
        )

    # 2.2 archive bomb (DOCX is a ZIP) — fast pre-check before scanner
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            entries = zf.infolist()
            if len(entries) > cfg.max_zip_entries:
                return IntakeContext(
                    outcome="BLOCKED", sha256=sha, size_bytes=size_bytes, filename=filename,
                    file_type=file_type, track=track,
                    version_id="", version_seq=0, uploaded_at=uploaded_at,
                    reason="archive_bomb",
                )
            total_compressed = sum(i.compress_size for i in entries)
            total_uncompressed = sum(i.file_size for i in entries)
            if total_compressed > 0 and total_uncompressed / total_compressed > cfg.max_compression_ratio:
                return IntakeContext(
                    outcome="BLOCKED", sha256=sha, size_bytes=size_bytes, filename=filename,
                    file_type=file_type, track=track,
                    version_id="", version_seq=0, uploaded_at=uploaded_at,
                    reason="archive_bomb",
                )
    except zipfile.BadZipFile:
        if file_type == "docx":
            return IntakeContext(
                outcome="BLOCKED", sha256=sha, size_bytes=size_bytes, filename=filename,
                file_type=file_type, track=track,
                version_id="", version_seq=0, uploaded_at=uploaded_at,
                reason="corrupt_zip",
            )

    # 2.1 %PDF- header + PDF object tree scan
    if file_type == "pdf":
        if not file_bytes.startswith(PDF_HEADER):
            return IntakeContext(
                outcome="REJECTED", sha256=sha, size_bytes=size_bytes, filename=filename,
                file_type=file_type, track=track,
                version_id="", version_seq=0, uploaded_at=uploaded_at,
                reason="not_a_pdf",
            )
        # Raw-byte scan for suspicious PDF objects
        for pattern in (b"/JS", b"/JavaScript", b"/EmbeddedFiles", b"/Launch", b"/OpenAction"):
            if pattern in file_bytes:
                return IntakeContext(
                    outcome="BLOCKED", sha256=sha, size_bytes=size_bytes, filename=filename,
                    file_type=file_type, track=track,
                    version_id="", version_seq=0, uploaded_at=uploaded_at,
                    reason=f"suspicious_pdf_object:{pattern.decode('utf-8', errors='replace')}",
                )

    # 2.3 cache lookup (sha256 + versions)
    cached = cache_get(sha, cfg.pipeline_version, cfg.rules_version)
    if cached is not None:
        return IntakeContext(
            outcome="DUPLICATE", sha256=sha, size_bytes=size_bytes, filename=filename,
            file_type=file_type, track=track,
            version_id="", version_seq=0, uploaded_at=uploaded_at,
            cache_hit=True, cached_output=cached,
            reason="cache_hit",
        )

    # 2.4 version registry with compare-and-swap
    existing = get_version(sha, track)
    if existing is not None:
        version_id, version_seq = existing
    else:
        version_seq = 1
        version_id = _build_version_id(sha, version_seq)
        try:
            registered = register_version(sha, track, upload_id, version_seq, "READY")
            if not registered:
                existing = get_version(sha, track)
                if existing is not None:
                    version_id, version_seq = existing
                else:
                    return IntakeContext(
                        outcome="EXPIRED", sha256=sha, size_bytes=size_bytes, filename=filename,
                        file_type=file_type, track=track,
                        version_id="", version_seq=0, uploaded_at=uploaded_at,
                        reason="version_register_failed",
                    )
        except Exception:
            return IntakeContext(
                outcome="EXPIRED", sha256=sha, size_bytes=size_bytes, filename=filename,
                file_type=file_type, track=track,
                version_id="", version_seq=0, uploaded_at=uploaded_at,
                reason="version_register_error",
            )

    # 2.5 open with fitz; reject encrypted / corrupt (PDF only)
    doc = None
    page_count = 0
    encrypted = False
    if file_type == "pdf":
        try:
            doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        except Exception as exc:
            return IntakeContext(
                outcome="REJECTED", sha256=sha, size_bytes=size_bytes, filename=filename,
                file_type=file_type, track=track,
                version_id=version_id, version_seq=version_seq, uploaded_at=uploaded_at,
                reason=f"cannot_open: {exc}",
            )
        if doc.is_encrypted:
            doc.close()
            return IntakeContext(
                outcome="REJECTED", sha256=sha, size_bytes=size_bytes, filename=filename,
                file_type=file_type, track=track,
                version_id=version_id, version_seq=version_seq, uploaded_at=uploaded_at,
                reason="encrypted",
            )
        if doc.page_count > cfg.max_pages:
            doc.close()
            return IntakeContext(
                outcome="REJECTED", sha256=sha, size_bytes=size_bytes, filename=filename,
                file_type=file_type, track=track,
                version_id=version_id, version_seq=version_seq, uploaded_at=uploaded_at,
                reason="too_many_pages",
            )
        for page in doc:
            try:
                pix = page.get_pixmap(dpi=cfg.dpi)
            except Exception as exc:
                doc.close()
                return IntakeContext(
                    outcome="REJECTED", sha256=sha, size_bytes=size_bytes, filename=filename,
                    file_type=file_type, track=track,
                    version_id=version_id, version_seq=version_seq, uploaded_at=uploaded_at,
                    reason=f"page_render_failed: {exc}",
                )
            if pix.width * pix.height > cfg.max_pixels:
                doc.close()
                return IntakeContext(
                    outcome="REJECTED", sha256=sha, size_bytes=size_bytes, filename=filename,
                    file_type=file_type, track=track,
                    version_id=version_id, version_seq=version_seq, uploaded_at=uploaded_at,
                    reason="page_exceeds_max_pixels",
                )
        page_count = doc.page_count
        encrypted = bool(doc.is_encrypted)

    # 2.6 Synchronous scan + CDR (Section 5.2)
    artifact = scan_file(file_bytes, cfg)
    scan_findings = [
        ScanFinding(
            rule_id=f.rule_id,
            stage=f.stage,
            severity=f.severity,
            description=f.description,
            matched_strings=f.matched_strings,
        )
        for f in artifact.findings
    ]

    if artifact.infected:
        # Don't close doc yet — pipeline will handle it
        return IntakeContext(
            outcome="BLOCKED", sha256=sha, size_bytes=size_bytes, filename=filename,
            file_type=file_type, track=track,
            version_id=version_id, version_seq=version_seq, uploaded_at=uploaded_at,
            reason=f"scan_infected:{artifact.threat_name or 'unknown'}",
            sanitized_artifact=artifact,
            scan_findings=scan_findings,
            doc=doc,
        )

    return IntakeContext(
        outcome="READY", sha256=sha, size_bytes=size_bytes, filename=filename,
        file_type=file_type, track=track,
        version_id=version_id, version_seq=version_seq, uploaded_at=uploaded_at,
        page_count=page_count, encrypted=encrypted,
        cache_hit=False, cached_output=None, doc=doc,
        sanitized_artifact=artifact,
        scan_findings=scan_findings,
    )
