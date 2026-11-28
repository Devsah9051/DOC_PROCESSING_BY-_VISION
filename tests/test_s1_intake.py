from __future__ import annotations

import io
import zipfile

import pymupdf
import pytest

from stages.s1_intake import intake, Stage1Error, IntakeContext, is_safe_filename
from app.scanner import magic_byte_check


def _make_docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<?xml version='1.0'?><Types/>")
        zf.writestr("word/document.xml", "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>")
    return buf.getvalue()


def _make_bomb_docx() -> bytes:
    """DOCX with high compression ratio (1000x repetition of same string)."""
    content = "<w:t>Hello</w:t>" * 50000
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<?xml version='1.0'?><Types/>")
        zf.writestr("word/document.xml", f"<w:document><w:body><w:p><w:r>{content}</w:r></w:p></w:body></w:document>")
    return buf.getvalue()


def _make_pdf_with_js() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello", fontsize=12)
    # Inject /JavaScript into the raw bytes
    raw = b"%PDF-1.4\n" + b"/JavaScript << /SomeJS >>\n" + b"dummy pdf content"
    return raw


# --- magic_byte_check ---

def test_detect_pdf(clean_pdf_bytes):
    ft, _, _ = magic_byte_check(clean_pdf_bytes)
    assert ft == "pdf"


def test_detect_docx():
    ft, _, _ = magic_byte_check(_make_docx())
    assert ft == "docx"


def test_detect_text():
    ft, _, _ = magic_byte_check(b"Hello world\nThis is plain text.")
    assert ft == "text"


def test_detect_unknown():
    ft, _, _ = magic_byte_check(b"\xff\xfe\x00binary")
    assert ft == "unknown"


# --- is_safe_filename ---

def test_safe_filename_valid():
    assert is_safe_filename("resume.pdf") is True
    assert is_safe_filename("my_file.v2.pdf") is True
    assert is_safe_filename("file-name.docx") is True


def test_safe_filename_invalid():
    assert is_safe_filename("file;rm -rf.pdf") is False
    assert is_safe_filename("") is False
    assert is_safe_filename("file with spaces.pdf") is False


# --- intake: PDF ---

def test_intake_clean_pdf_ready(clean_pdf_bytes):
    ctx = intake(clean_pdf_bytes, "resume.pdf", "u1")
    assert ctx.outcome == "READY"
    assert ctx.file_type == "pdf"
    assert ctx.track == "resume"
    assert ctx.doc is not None
    assert ctx.page_count > 0
    ctx.doc.close()


def test_intake_clean_pdf_jd_track(clean_pdf_bytes):
    ctx = intake(clean_pdf_bytes, "job_description.pdf", "u1")
    assert ctx.track == "job_description"
    ctx.doc.close()


def test_intake_corrupt_pdf_rejected(corrupt_pdf):
    ctx = intake(corrupt_pdf, "resume.pdf", "u1")
    assert ctx.outcome == "REJECTED"
    assert ctx.reason.startswith("cannot_open")
    assert ctx.doc is None


def test_intake_unsafe_filename_rejected(clean_pdf_bytes):
    ctx = intake(clean_pdf_bytes, "file;rm -rf.pdf", "u1")
    assert ctx.outcome == "REJECTED"
    assert ctx.reason == "unsafe_filename"


def test_intake_oversized_pdf_rejected(oversized_pdf):
    ctx = intake(oversized_pdf, "resume.pdf", "u1")
    assert ctx.outcome == "REJECTED"
    assert ctx.reason.startswith("page_exceeds_max_pixels") or ctx.reason.startswith("page_render_failed")


# --- intake: DOCX ---

def test_intake_docx_ready():
    ctx = intake(_make_docx(), "resume.docx", "u1")
    assert ctx.outcome == "READY"
    assert ctx.file_type == "docx"
    assert ctx.doc is None


def test_intake_docx_archive_bomb_blocked():
    ctx = intake(_make_bomb_docx(), "resume.docx", "u1")
    assert ctx.outcome == "BLOCKED"
    assert "archive_bomb" in ctx.reason or "ZIP_BOMB_RATIO" in ctx.reason


def test_intake_docx_unsafe_filename_rejected():
    ctx = intake(_make_docx(), "file;evil.docx", "u1")
    assert ctx.outcome == "REJECTED"
    assert ctx.reason == "unsafe_filename"


# --- intake: plain text ---

def test_intake_text_ready():
    ctx = intake(b"Hello world\nThis is a resume.", "resume.txt", "u1")
    assert ctx.outcome == "READY"
    assert ctx.file_type == "text"
    assert ctx.doc is None


# --- intake: not a PDF ---

def test_intake_not_a_pdf_rejected():
    ctx = intake(b"\x89PNG\r\n\x1a\n", "resume.pdf", "u1")
    assert ctx.outcome == "REJECTED"
    assert ctx.reason == "unsupported_file_type"


# --- intake: suspicious PDF objects ---

def test_intake_pdf_with_javascript_blocked():
    ctx = intake(_make_pdf_with_js(), "resume.pdf", "u1")
    assert ctx.outcome == "BLOCKED"
    assert "JavaScript" in ctx.reason


# --- intake: version_id and version_seq ---

def test_intake_version_fields(clean_pdf_bytes):
    ctx = intake(clean_pdf_bytes, "resume.pdf", "u1")
    assert ctx.version_id != ""
    assert ctx.version_seq >= 1
    assert ctx.uploaded_at > 0


# --- intake: DUPLICATE via cache ---

def test_intake_cache_hit_duplicate(clean_pdf_bytes, monkeypatch):
    from app import db

    cached = {"sections": [], "tokens": [], "verdict": {"status": "CLEAN", "score": 0, "rules": [], "reasons": []}}
    monkeypatch.setattr(db, "cache_get", lambda *a, **k: cached)
    monkeypatch.setattr(__import__("stages.s1_intake", fromlist=["cache_get"]), "cache_get", lambda *a, **k: cached)

    ctx = intake(clean_pdf_bytes, "resume.pdf", "u1")
    assert ctx.outcome == "DUPLICATE"
    assert ctx.cache_hit is True
    assert ctx.cached_output == cached


# --- pipeline-level: REJECTED outcome → FAILED ---

def test_pipeline_rejected_intake_failed(clean_pdf_bytes, monkeypatch):
    from app import pipeline as pl

    def fake_intake(*a, **k):
        return IntakeContext(
            outcome="REJECTED", sha256="abc", size_bytes=10, filename="x.pdf",
            file_type="pdf", track="resume", version_id="", version_seq=0,
            uploaded_at=1.0, reason="unsafe_filename",
        )

    monkeypatch.setattr(pl, "intake", fake_intake)
    out = pl.run_phase1(b"%PDF-1.4 dummy", "x.pdf", "u1")
    assert out.verdict.status == "FAILED"
    assert "unsafe_filename" in out.verdict.reasons[0]


# --- pipeline-level: BLOCKED outcome → QUARANTINE ---

def test_pipeline_blocked_intake_quarantine(clean_pdf_bytes, monkeypatch):
    from app import pipeline as pl

    def fake_intake(*a, **k):
        return IntakeContext(
            outcome="BLOCKED", sha256="abc", size_bytes=10, filename="x.pdf",
            file_type="pdf", track="resume", version_id="", version_seq=0,
            uploaded_at=1.0, reason="archive_bomb",
        )

    monkeypatch.setattr(pl, "intake", fake_intake)
    out = pl.run_phase1(b"%PDF-1.4 dummy", "x.pdf", "u1")
    assert out.verdict.status == "QUARANTINE"
    assert "archive_bomb" in out.verdict.reasons[0]


# --- fixtures ---

@pytest.fixture
def clean_pdf_bytes():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "Jane Doe", fontsize=16)
    page.insert_text((72, 96), "Software Engineer", fontsize=12)
    buf = io.BytesIO()
    doc.save(buf, deflate=True)
    doc.close()
    return buf.getvalue()


@pytest.fixture
def corrupt_pdf():
    return b"%PDF-1.4\ncorrupt garbage not a real pdf structure"


@pytest.fixture
def oversized_pdf():
    buf = io.BytesIO()
    doc = pymupdf.open()
    page = doc.new_page(width=10000, height=10000)
    page.insert_text((72, 72), "huge", fontsize=12)
    doc.save(buf, deflate=True)
    doc.close()
    return buf.getvalue()
