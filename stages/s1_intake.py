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
from app.db import cache_get, get_version, register_version, scan_result_insert_full
from app.scanner import scan_file, SanitizedArtifact, ScanFinding, magic_byte_check

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
    job: Optional[str] = None  # job id (nullable; spec §5.3 key component)
    version_id: str = ""
    version_seq: int = 0
    uploaded_at: float = 0.0
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


def intake(file_bytes: bytes, filename: str, upload_id: str, cfg=config, job: Optional[str] = None) -> IntakeContext:
    sha = sha256_of(file_bytes)
    size_bytes = len(file_bytes)
    file_type, _, _ = magic_byte_check(file_bytes)
    track = detect_track(filename)
    uploaded_at = time.time()
    raw_findings: list[ScanFinding] = []

    # Derive job from filename for job_description track (spec §5.3 key: owner+job+track)
    if job is None and track == "job_description":
        stem = os.path.splitext(os.path.basename(filename))[0]
        job = stem or None

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
                pattern_name = pattern.decode("utf-8", errors="replace")
                raw_findings.append(ScanFinding(
                    rule_id=f"SUSPICIOUS_PDF_OBJECT:{pattern_name}",
                    stage="magic",
                    scan_layer="raw",
                    severity="High",
                    description=f"Suspicious PDF object detected: {pattern_name}",
                    matched_strings=[pattern_name],
                ))
                return IntakeContext(
                    outcome="BLOCKED", sha256=sha, size_bytes=size_bytes, filename=filename,
                    file_type=file_type, track=track,
                    version_id="", version_seq=0, uploaded_at=uploaded_at,
                    reason=f"suspicious_pdf_object:{pattern_name}",
                    scan_findings=raw_findings,
                )

    # ZIP bomb check (DOCX is a ZIP) — always runs, independent of scan_enabled
    if file_type == "docx":
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                entries = zf.infolist()
                if len(entries) > cfg.max_zip_entries:
                    raw_findings.append(ScanFinding(
                        rule_id="ZIP_ENTRY_COUNT",
                        stage="zip",
                        scan_layer="zip",
                        severity="High",
                        description=f"Too many ZIP entries: {len(entries)} > {cfg.max_zip_entries}",
                    ))
                    return IntakeContext(
                        outcome="BLOCKED", sha256=sha, size_bytes=size_bytes, filename=filename,
                        file_type=file_type, track=track,
                        version_id="", version_seq=0, uploaded_at=uploaded_at,
                        reason="archive_bomb",
                        scan_findings=raw_findings,
                    )
                total_compressed = sum(i.compress_size for i in entries)
                total_uncompressed = sum(i.file_size for i in entries)
                if total_compressed > 0:
                    ratio = total_uncompressed / total_compressed
                    if ratio > cfg.max_compression_ratio:
                        raw_findings.append(ScanFinding(
                            rule_id="ZIP_BOMB_RATIO",
                            stage="zip",
                            scan_layer="zip",
                            severity="High",
                            description=f"Compression ratio {ratio:.1f}x > {cfg.max_compression_ratio}x",
                        ))
                        return IntakeContext(
                            outcome="BLOCKED", sha256=sha, size_bytes=size_bytes, filename=filename,
                            file_type=file_type, track=track,
                            version_id="", version_seq=0, uploaded_at=uploaded_at,
                            reason="archive_bomb",
                            scan_findings=raw_findings,
                        )
                for entry in entries:
                    if ".." in entry.filename or entry.filename.startswith("/"):
                        raw_findings.append(ScanFinding(
                            rule_id="ZIP_PATH_TRAVERSAL",
                            stage="zip",
                            scan_layer="zip",
                            severity="High",
                            description=f"Path traversal in ZIP entry: {entry.filename}",
                        ))
                        return IntakeContext(
                            outcome="BLOCKED", sha256=sha, size_bytes=size_bytes, filename=filename,
                            file_type=file_type, track=track,
                            version_id="", version_seq=0, uploaded_at=uploaded_at,
                            reason="archive_bomb",
                            scan_findings=raw_findings,
                        )
        except zipfile.BadZipFile:
            raw_findings.append(ScanFinding(
                rule_id="BAD_ZIP",
                stage="zip",
                scan_layer="zip",
                severity="High",
                description="DOCX file is not a valid ZIP archive",
            ))
            return IntakeContext(
                outcome="BLOCKED", sha256=sha, size_bytes=size_bytes, filename=filename,
                file_type=file_type, track=track,
                version_id="", version_seq=0, uploaded_at=uploaded_at,
                reason="corrupt_zip",
                scan_findings=raw_findings,
            )

    # Open PDF once with pymupdf; use the same handle for encryption + structural checks
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
                version_id="", version_seq=0, uploaded_at=uploaded_at,
                reason=f"cannot_open: {exc}",
            )
        if doc.is_encrypted:
            doc.close()
            return IntakeContext(
                outcome="REJECTED", sha256=sha, size_bytes=size_bytes, filename=filename,
                file_type=file_type, track=track,
                version_id="", version_seq=0, uploaded_at=uploaded_at,
                reason="encrypted",
            )
        # Structural check: iterate pages with read_contents() on the same handle
        try:
            for page in doc:
                _ = page.read_contents()
        except Exception as exc:
            doc.close()
            return IntakeContext(
                outcome="REJECTED", sha256=sha, size_bytes=size_bytes, filename=filename,
                file_type=file_type, track=track,
                version_id="", version_seq=0, uploaded_at=uploaded_at,
                reason=f"page_read_failed: {exc}",
            )
        if doc.page_count > cfg.max_pages:
            doc.close()
            return IntakeContext(
                outcome="REJECTED", sha256=sha, size_bytes=size_bytes, filename=filename,
                file_type=file_type, track=track,
                version_id="", version_seq=0, uploaded_at=uploaded_at,
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
                    version_id="", version_seq=0, uploaded_at=uploaded_at,
                    reason=f"page_render_failed: {exc}",
                )
            if pix.width * pix.height > cfg.max_pixels:
                doc.close()
                return IntakeContext(
                    outcome="REJECTED", sha256=sha, size_bytes=size_bytes, filename=filename,
                    file_type=file_type, track=track,
                    version_id="", version_seq=0, uploaded_at=uploaded_at,
                    reason="page_exceeds_max_pixels",
                )
        page_count = doc.page_count
        encrypted = bool(doc.is_encrypted)

    # 2.3 cache lookup (sha256 + versions)
    cached = cache_get(sha, cfg.pipeline_version, cfg.rules_version)
    if cached is not None:
        return IntakeContext(
            outcome="DUPLICATE", sha256=sha, size_bytes=size_bytes, filename=filename,
            file_type=file_type, track=track, job=job,
            version_id="", version_seq=0, uploaded_at=uploaded_at,
            cache_hit=True, cached_output=cached,
            reason="cache_hit",
        )

    # 2.6 Synchronous scan + CDR (Section 5.2) — gated by scan_enabled
    artifact: Optional[SanitizedArtifact] = None
    scan_findings: list[ScanFinding] = []
    if cfg.scan_enabled:
        artifact = scan_file(file_bytes, cfg, sha256=sha, doc=doc)
        scan_findings = [
            ScanFinding(
                rule_id=f.rule_id,
                stage=f.stage,
                scan_layer=f.scan_layer,
                severity=f.severity,
                description=f.description,
                matched_strings=f.matched_strings,
            )
            for f in artifact.findings
        ]

    if artifact is not None and artifact.infected:
        # Don't close doc yet — pipeline will handle it
        return IntakeContext(
            outcome="BLOCKED", sha256=sha, size_bytes=size_bytes, filename=filename,
            file_type=file_type, track=track,
            version_id="", version_seq=0, uploaded_at=uploaded_at,
            reason=f"scan_infected:{artifact.threat_name or 'unknown'}",
            sanitized_artifact=artifact,
            scan_findings=scan_findings,
            doc=doc,
        )

    # 2.4 version registry with compare-and-swap — only after ALL checks pass
    # A REJECTED/BLOCKED file must NOT leave a READY row in version_registry
    existing = get_version(upload_id, job, track)
    if existing is not None:
        version_id, version_seq = existing
    else:
        version_seq = 1
        version_id = _build_version_id(sha, version_seq)
        try:
            registered = register_version(upload_id, job, track, version_seq, "READY", sha256=sha)
            if not registered:
                existing = get_version(upload_id, job, track)
                if existing is not None:
                    version_id, version_seq = existing
                else:
                    return IntakeContext(
                        outcome="EXPIRED", sha256=sha, size_bytes=size_bytes, filename=filename,
                        file_type=file_type, track=track, job=job,
                        version_id="", version_seq=0, uploaded_at=uploaded_at,
                        reason="version_register_failed",
                    )
        except Exception:
            return IntakeContext(
                outcome="EXPIRED", sha256=sha, size_bytes=size_bytes, filename=filename,
                file_type=file_type, track=track, job=job,
                version_id="", version_seq=0, uploaded_at=uploaded_at,
                reason="version_register_error",
            )

    if artifact is not None:
        return IntakeContext(
            outcome="READY", sha256=sha, size_bytes=size_bytes, filename=filename,
            file_type=file_type, track=track, job=job,
            version_id=version_id, version_seq=version_seq, uploaded_at=uploaded_at,
            page_count=page_count, encrypted=encrypted,
            cache_hit=False, cached_output=None, doc=doc,
            sanitized_artifact=artifact,
            scan_findings=scan_findings,
        )

    # scan_enabled=False → clean passthrough, no CDR, no findings
    # Use original bytes as sanitized_bytes so downstream stages have something to process
    passthrough_artifact = SanitizedArtifact(
        sha256=sha,
        raw_sha256=sha,
        file_type=file_type,
        original_size=size_bytes,
        sanitized_size=size_bytes,
        sanitized_bytes=file_bytes,
        scan_engine="passthrough",
        infected=False,
        threat_name=None,
        findings=[],
        cdr_applied=False,
        cdr_method=None,
        scanned_at=uploaded_at,
    )
    return IntakeContext(
        outcome="READY", sha256=sha, size_bytes=size_bytes, filename=filename,
        file_type=file_type, track=track, job=job,
        version_id=version_id, version_seq=version_seq, uploaded_at=uploaded_at,
        page_count=page_count, encrypted=encrypted,
        cache_hit=False, cached_output=None, doc=doc,
        sanitized_artifact=passthrough_artifact,
        scan_findings=[],
    )
