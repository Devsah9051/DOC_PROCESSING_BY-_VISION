from __future__ import annotations

from unittest import mock

import hashlib
import io
import pytest

from app.scanner import (
    scan_file,
    scan_stub,
    scan_clamav,
    magic_byte_check,
    zip_bomb_guard,
    yara_scan,
    cdr_reconstruct_pdf_targeted,
    cdr_reconstruct_pdf_full,
    cdr_reconstruct_docx,
    SanitizedArtifact,
    ScanFinding,
)
from app.schemas import SanitizedArtifact as SanitizedArtifactSchema, ScanFinding as ScanFindingSchema


# EICAR test string (industry-standard harmless malware test signature)
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
CLEAN_PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 612 792]>>endobj xref 0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \ntrailer<</Size 4/Root 1 0 R>>startxref 178\n%%EOF\n"
CLEAN_TEXT = b"Jane Doe\nSoftware Engineer\nPython developer at Acme Corp\n"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestMagicByteCheck:
    def test_pdf_detected(self):
        ftype, finding, _ = magic_byte_check(CLEAN_PDF)
        assert ftype == "pdf"
        assert finding is None

    def test_text_detected(self):
        ftype, finding, _ = magic_byte_check(CLEAN_TEXT)
        assert ftype == "text"
        assert finding is None

    def test_unknown_rejected(self):
        ftype, finding, _ = magic_byte_check(b"\xff\xfe\x00\x01binary")
        assert ftype == "unknown"
        assert finding is not None
        assert finding.severity == "High"
        assert finding.rule_id == "INVALID_FILE_TYPE"


class TestZipBombGuard:
    def test_non_docx_passes(self):
        finding = zip_bomb_guard(CLEAN_PDF, "pdf", type("C", (), {"max_zip_entries": 10000, "max_compression_ratio": 100})())
        assert finding is None

    def test_clean_docx_passes(self):
        import zipfile, io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("document.xml", "<w:document/>")
        finding = zip_bomb_guard(buf.getvalue(), "docx", type("C", (), {"max_zip_entries": 10000, "max_compression_ratio": 100})())
        assert finding is None

    def test_path_traversal_blocked(self):
        import zipfile, io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../../etc/passwd", "evil")
        finding = zip_bomb_guard(buf.getvalue(), "docx", type("C", (), {"max_zip_entries": 10000, "max_compression_ratio": 100})())
        assert finding is not None
        assert finding.rule_id == "ZIP_PATH_TRAVERSAL"

    def test_bad_zip_blocked(self):
        finding = zip_bomb_guard(b"not a zip", "docx", type("C", (), {"max_zip_entries": 10000, "max_compression_ratio": 100})())
        assert finding is not None
        assert finding.rule_id == "BAD_ZIP"


class TestYaraScan:
    def test_eicar_detected(self):
        findings = yara_scan(EICAR)
        assert len(findings) > 0
        assert any(f.severity == "High" for f in findings)

    def test_clean_file_no_findings(self):
        findings = yara_scan(CLEAN_PDF)
        # Clean PDF should not match any YARA rules
        assert len(findings) == 0


class TestCDR:
    def test_cdr_pdf(self):
        import pymupdf
        # Create a simple PDF
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello World", fontsize=12)
        buf = __import__("io").BytesIO()
        doc.save(buf, deflate=True)
        doc.close()
        pdf_bytes_val = buf.getvalue()

        sanitized, method, applied = cdr_reconstruct_pdf_full(pdf_bytes_val, dpi=200)
        assert applied is True
        assert "pdf_to_images" in method
        assert len(sanitized) > 0

    def test_cdr_docx(self):
        import zipfile, io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("[Content_Types].xml", "<?xml version='1.0'?><Types/>")
            zf.writestr("word/document.xml", "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>")
        sanitized, method, applied = cdr_reconstruct_docx(buf.getvalue())
        assert applied is True
        assert method == "docx_to_clean_text"
        assert b"Hello" in sanitized


class TestScanFile:
    def test_clean_pdf_returns_artifact(self):
        result = scan_file(CLEAN_PDF)
        assert isinstance(result, SanitizedArtifact)
        assert result.sha256 == _sha(CLEAN_PDF)
        assert result.file_type == "pdf"
        assert result.scan_engine == "yara+cdr"
        assert result.infected is False
        assert result.cdr_applied is False  # clean files skip CDR, keep text layer
        assert result.sanitized_bytes == CLEAN_PDF  # original bytes preserved
        assert len(result.findings) == 0

    def test_eicar_detected_infected(self):
        result = scan_file(EICAR)
        assert result.infected is True
        assert result.threat_name is not None
        assert "EICAR" in result.threat_name
        assert len(result.findings) > 0
        assert any(f.severity == "High" for f in result.findings)

    def test_clean_text_returns_artifact(self):
        result = scan_file(CLEAN_TEXT)
        assert result.file_type == "text"
        assert result.infected is False
        assert result.cdr_applied is False  # text passthrough
        assert result.sanitized_bytes == CLEAN_TEXT
        assert result.raw_sha256 == _sha(CLEAN_TEXT)

    def test_raw_sha256_preserved(self):
        """raw_sha256 always equals the hash of the original upload, even after CDR."""
        result = scan_file(CLEAN_PDF)
        assert result.raw_sha256 == _sha(CLEAN_PDF)
        assert result.sha256 == _sha(CLEAN_PDF)

    def test_text_with_external_links_medium_cdr_skipped(self):
        """Text file with http:// links gets Medium finding but CDR skipped (text passthrough)."""
        text_with_link = b"See https://example.com for more details."
        result = scan_file(text_with_link)
        assert result.file_type == "text"
        # External links are Medium severity → not infected
        assert result.infected is False
        # Text files skip CDR (passthrough)
        assert result.cdr_applied is False
        assert result.sanitized_bytes == text_with_link
        assert len(result.findings) > 0
        assert any("external_link" in f.rule_id.lower() for f in result.findings)

    def test_pdf_structural_invalid_blocked(self):
        """Malformed PDF with valid header but corrupt structure → BLOCKED."""
        bad_pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"  # incomplete xref
        result = scan_file(bad_pdf)
        assert result.file_type == "pdf"
        assert result.infected is True
        assert result.cdr_applied is False


class TestScanFindingSchema:
    def test_scan_finding_schema(self):
        sf = ScanFindingSchema(
            rule_id="YARA_PDF_JAVASCRIPT",
            stage="yara",
            scan_layer="yara",
            severity="High",
            description="YARA rule matched: pdf_javascript",
            matched_strings=["/JS"],
        )
        assert sf.rule_id == "YARA_PDF_JAVASCRIPT"
        assert sf.stage == "yara"
        assert sf.severity == "High"

    def test_sanitized_artifact_schema(self):
        sha = _sha(CLEAN_PDF)
        sa = SanitizedArtifactSchema(
            sha256=sha,
            raw_sha256=sha,
            file_type="pdf",
            original_size=len(CLEAN_PDF),
            sanitized_size=1000,
            scan_engine="yara+cdr",
            infected=False,
            cdr_applied=True,
            cdr_method="pdf_to_images_200dpi",
        )
        assert sa.sha256 == sha
        assert sa.infected is False
        assert sa.cdr_applied is True


class TestScanStubCompat:
    def test_scan_stub_legacy(self):
        infected, threat, payload = scan_stub(CLEAN_PDF)
        assert infected is False
        assert payload["engine"] == "yara+cdr"

    def test_scan_stub_eicar(self):
        infected, threat, payload = scan_stub(EICAR)
        assert infected is True
        assert threat is not None

    def test_scan_clamav_legacy(self):
        infected, threat, payload = scan_clamav(CLEAN_PDF)
        assert infected is False
        assert payload["clamav_fallback"] is True
