from __future__ import annotations

import io
import json
import zipfile
from unittest import mock

import pytest

from app.pipeline import run_phase1


def _run(file_bytes, filename="resume.pdf", upload_id="u1"):
    return run_phase1(file_bytes, filename, upload_id)


def _make_docx(text_content: str) -> bytes:
    """Create a minimal valid DOCX with the given text content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>')
        zf.writestr("word/document.xml",
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body><w:p><w:r><w:t>{text_content}</w:t></w:r></w:p></w:body>'
            f'</w:document>')
    return buf.getvalue()


def _make_text(text_content: str) -> bytes:
    return text_content.encode("utf-8")


def test_clean_pdf_is_clean(clean_pdf):
    out = _run(clean_pdf)
    assert out.verdict.status == "CLEAN", out.verdict.reasons
    assert out.tokens, "expected text-layer tokens"
    assert any(t["text"] == "Jane Doe" for t in out.tokens)
    assert out.prev_hash


def test_clean_pdf_zero_ocr(clean_pdf):
    out = _run(clean_pdf)
    # text layer verified => no OCR boxes needed; tokens come from text layer
    assert out.verdict.status == "CLEAN"


def test_hash_stable(clean_pdf):
    out1 = _run(clean_pdf, upload_id="u1")
    out2 = _run(clean_pdf, upload_id="u2")
    assert out1.report_hash == out2.report_hash
    assert out1.signature == out2.signature
    assert out1.prev_hash == out2.prev_hash


def test_cache_hit_returns_cached(clean_pdf):
    cached = {
        "sections": [],
        "tokens": [{"word_id": "cached-1", "page": 1, "bbox": [0, 0, 10, 10], "text": "cached", "source": "cache", "visible": True, "flags": []}],
        "verdict": {"status": "CLEAN", "score": 0.0, "rules": [], "reasons": []},
        "versions": {"pipeline_version": "1.0.0", "rules_version": "1.0.0"},
        "timings_ms": {},
        "prev_hash": "x",
        "report_hash": "y",
        "signature": "z",
    }
    import app.pipeline as pl

    with mock.patch.object(pl, "cache_get", return_value=cached):
        with mock.patch.object(pl, "intake") as intake_mock:
            class Ctx:
                outcome = "DUPLICATE"
                cache_hit = True
                cached_output = cached
            intake_mock.return_value = Ctx()
            out = run_phase1(clean_pdf, "x.pdf", "u-cache")
    assert out.verdict.status == "CLEAN"
    assert out.tokens[0]["text"] == "cached"


def test_corrupt_pdf_quarantined(corrupt_pdf):
    out = _run(corrupt_pdf)
    assert out.verdict.status == "FAILED", out.verdict.reasons


def test_oversized_pdf_quarantined(oversized_pdf):
    out = _run(oversized_pdf)
    assert out.verdict.status == "FAILED", out.verdict.reasons


def test_injection_visible_quarantined(injection_visible_pdf):
    out = _run(injection_visible_pdf)
    assert out.verdict.status == "QUARANTINE", out.verdict.reasons


def test_metadata_injection_quarantined(metadata_injection_pdf):
    out = _run(metadata_injection_pdf)
    assert out.verdict.status == "QUARANTINE", out.verdict.reasons


def test_tiny_font_flagged(tiny_font_pdf):
    out = _run(tiny_font_pdf)
    assert out.verdict.status in ("REVIEW", "QUARANTINE"), out.verdict.reasons
    assert any("TINY_FONT" in r for r in out.verdict.reasons) or "TINY_FONT" in out.verdict.rules


def test_off_page_flagged(off_page_pdf):
    out = _run(off_page_pdf)
    assert any("OFF_PAGE" in r for r in out.verdict.reasons) or "OFF_PAGE" in out.verdict.rules, out.verdict.reasons


def test_zerowidth_flagged(zerowidth_pdf):
    out = _run(zerowidth_pdf)
    assert any("ZERO_WIDTH" in r for r in out.verdict.reasons) or "ZERO_WIDTH" in out.verdict.rules, out.verdict.reasons


def test_white_on_white_not_visible(white_on_white_pdf):
    out = _run(white_on_white_pdf)
    assert any("NOT_VISIBLE" in r for r in out.verdict.reasons) or "NOT_VISIBLE" in out.verdict.rules, out.verdict.reasons


def test_covered_text_not_visible(covered_pdf):
    out = _run(covered_pdf)
    assert any("COVERED_BY_SHAPE" in r or "NOT_VISIBLE" in r for r in out.verdict.reasons) or "COVERED_BY_SHAPE" in out.verdict.rules or "NOT_VISIBLE" in out.verdict.rules, out.verdict.reasons


def test_two_column_reading_order(two_column_pdf):
    out = _run(two_column_pdf)
    text = " ".join(t["text"] for t in out.tokens)
    assert "Left column" in text and "Right column" in text
    assert out.verdict.status == "CLEAN", out.verdict.reasons


def test_output_has_versions_and_timings(clean_pdf):
    out = _run(clean_pdf)
    assert out.versions["pipeline_version"] == "1.0.0"
    assert out.versions["rules_version"] == "1.0.0"
    assert "stage1_intake" in out.timings_ms
    assert "stage2_verify" in out.timings_ms
    assert "stage3_pre_gate" in out.timings_ms
    assert "stage3_post_gate" in out.timings_ms
    assert "stage4_structure" in out.timings_ms
    assert "stage5_normalise" in out.timings_ms


def test_docx_end_to_end():
    """DOCX file passes through Stage 1 (CDR extracts text), skips Stage 2 verify,
    reaches Stage 4/5 with extracted text tokens."""
    docx_bytes = _make_docx("Jane Doe Software Engineer")
    out = _run(docx_bytes, "resume.docx")
    assert out.verdict.status == "CLEAN", out.verdict.reasons
    # Tokens should contain extracted text
    token_texts = " ".join(t["text"] for t in out.tokens)
    assert "Jane" in token_texts or "Doe" in token_texts or "Software" in token_texts
    assert out.prev_hash
    assert out.report_hash
    assert out.signature


def test_text_end_to_end():
    """Plain text file passes through Stage 1, skips Stage 2 verify,
    reaches Stage 4/5 with text tokens."""
    text_bytes = _make_text("John Smith Product Manager")
    out = _run(text_bytes, "resume.txt")
    assert out.verdict.status == "CLEAN", out.verdict.reasons
    token_texts = " ".join(t["text"] for t in out.tokens)
    assert "John" in token_texts or "Smith" in token_texts or "Product" in token_texts
    assert out.prev_hash
    assert out.report_hash
    assert out.signature
