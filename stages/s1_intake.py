from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass

import pymupdf

from app.config import config
from app.db import cache_get

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
PDF_HEADER = b"%PDF-"


class Stage1Error(Exception):
    """Fatal intake failure; the pipeline converts this to QUARANTINED."""


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_safe_filename(filename: str) -> bool:
    name = os.path.basename(filename)
    if not name or name in (".", ".."):
        return False
    return SAFE_NAME_RE.match(name) is not None


@dataclass
class IntakeContext:
    sha256: str
    size_bytes: int
    filename: str
    page_count: int
    encrypted: bool
    cache_hit: bool
    cached_output: dict | None
    doc: object | None = None  # pymupdf Document (closed when not cache hit and caller proceeds)


def intake(file_bytes: bytes, filename: str, upload_id: str, cfg=config) -> IntakeContext:
    # 2.1 size cap
    if len(file_bytes) > cfg.max_bytes:
        raise Stage1Error("file_exceeds_max_bytes")
    # 2.1 safe filename
    if not is_safe_filename(filename):
        raise Stage1Error("unsafe_filename")
    # 2.1 %PDF- header
    if not file_bytes.startswith(PDF_HEADER):
        raise Stage1Error("not_a_pdf")
    # 2.2 sha256
    sha = sha256_of(file_bytes)
    # 2.3 cache lookup (sha256 + versions)
    cached = cache_get(sha, cfg.pipeline_version, cfg.rules_version)
    if cached is not None:
        return IntakeContext(
            sha256=sha,
            size_bytes=len(file_bytes),
            filename=filename,
            page_count=0,
            encrypted=False,
            cache_hit=True,
            cached_output=cached,
        )
    # 2.4 open with fitz; reject encrypted / corrupt
    try:
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:  # corrupt / unreadable
        raise Stage1Error(f"cannot_open: {exc}") from exc
    if doc.is_encrypted:
        doc.close()
        raise Stage1Error("encrypted")
    # pages > max_pages
    if doc.page_count > cfg.max_pages:
        doc.close()
        raise Stage1Error("too_many_pages")
    # any page whose render size > max_pixels
    for page in doc:
        pix = page.get_pixmap(dpi=cfg.dpi)
        if pix.width * pix.height > cfg.max_pixels:
            doc.close()
            raise Stage1Error("page_exceeds_max_pixels")
    return IntakeContext(
        sha256=sha,
        size_bytes=len(file_bytes),
        filename=filename,
        page_count=doc.page_count,
        encrypted=bool(doc.is_encrypted),
        cache_hit=False,
        cached_output=None,
        doc=doc,
    )
