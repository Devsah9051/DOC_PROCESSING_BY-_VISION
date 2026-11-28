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


# --- Stream B: version_registry key (owner, job, track) per spec §5.3 ---

def test_intake_same_sha_track_different_job_distinct_versions(clean_pdf_bytes, monkeypatch):
    """Same sha256 + track but different job → register_version called with different job (spec §5.3)."""
    from app import db
    import stages.s1_intake as s1

    calls = []

    def fake_get_version(owner, job, track):
        return None  # no existing version

    def fake_register_version(owner, job, track, version_seq, outcome, sha256=None):
        calls.append((owner, job, track, version_seq, outcome, sha256))
        return True

    monkeypatch.setattr(db, "get_version", fake_get_version)
    monkeypatch.setattr(db, "register_version", fake_register_version)
    monkeypatch.setattr(s1, "get_version", fake_get_version)
    monkeypatch.setattr(s1, "register_version", fake_register_version)

    # Same file, same owner, same track, different job
    ctx1 = intake(clean_pdf_bytes, "jd_engineer.pdf", "u1", job="eng-1")
    ctx2 = intake(clean_pdf_bytes, "jd_manager.pdf", "u1", job="mgr-1")

    assert ctx1.outcome == "READY"
    assert ctx2.outcome == "READY"
    assert ctx1.job == "eng-1"
    assert ctx2.job == "mgr-1"
    assert ctx1.track == ctx2.track == "job_description"

    # register_version called with different jobs
    job_args = [c[1] for c in calls]
    assert "eng-1" in job_args
    assert "mgr-1" in job_args
    assert len(calls) == 2


def test_intake_rejected_file_no_ready_row(clean_pdf_bytes, monkeypatch):
    """Rejected file must NOT call register_version (no READY row in version_registry)."""
    from app import db
    import stages.s1_intake as s1

    register_calls = []

    def fake_get_version(owner, job, track):
        return None

    def fake_register_version(owner, job, track, version_seq, outcome, sha256=None):
        register_calls.append((owner, job, track))
        return True

    monkeypatch.setattr(db, "get_version", fake_get_version)
    monkeypatch.setattr(db, "register_version", fake_register_version)
    monkeypatch.setattr(s1, "get_version", fake_get_version)
    monkeypatch.setattr(s1, "register_version", fake_register_version)

    # Unsafe filename → REJECTED, should not register
    ctx = intake(clean_pdf_bytes, "file;rm -rf.pdf", "u1")
    assert ctx.outcome == "REJECTED"
    assert ctx.reason == "unsafe_filename"
    assert len(register_calls) == 0, "register_version must not be called for REJECTED files"


def test_intake_job_derived_from_filename_jd_track(clean_pdf_bytes, monkeypatch):
    """job is derived from filename for job_description track when not explicitly passed."""
    from app import db
    import stages.s1_intake as s1

    register_calls = []

    def fake_get_version(owner, job, track):
        return None

    def fake_register_version(owner, job, track, version_seq, outcome, sha256=None):
        register_calls.append((owner, job, track))
        return True

    monkeypatch.setattr(db, "get_version", fake_get_version)
    monkeypatch.setattr(db, "register_version", fake_register_version)
    monkeypatch.setattr(s1, "get_version", fake_get_version)
    monkeypatch.setattr(s1, "register_version", fake_register_version)

    ctx = intake(clean_pdf_bytes, "senior_engineer_jd.pdf", "u1")
    assert ctx.track == "job_description"
    assert ctx.job == "senior_engineer_jd"  # derived from filename stem

    # register_version called with derived job
    assert len(register_calls) == 1
    assert register_calls[0][1] == "senior_engineer_jd"


def test_intake_job_none_for_resume_track(clean_pdf_bytes, monkeypatch):
    """job is None for resume track (not job_description)."""
    from app import db
    import stages.s1_intake as s1

    register_calls = []

    def fake_get_version(owner, job, track):
        return None

    def fake_register_version(owner, job, track, version_seq, outcome, sha256=None):
        register_calls.append((owner, job, track))
        return True

    monkeypatch.setattr(db, "get_version", fake_get_version)
    monkeypatch.setattr(db, "register_version", fake_register_version)
    monkeypatch.setattr(s1, "get_version", fake_get_version)
    monkeypatch.setattr(s1, "register_version", fake_register_version)

    ctx = intake(clean_pdf_bytes, "resume.pdf", "u1")
    assert ctx.track == "resume"
    assert ctx.job is None

    # register_version called with job=None
    assert len(register_calls) == 1
    assert register_calls[0][1] is None
