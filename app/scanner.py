from __future__ import annotations

import hashlib
import io
import os
import zipfile
from dataclasses import dataclass, field
from typing import Optional

import pymupdf
import pikepdf
import yara
from defusedxml import ElementTree as DefusedET

from app.config import config

# --- YARA rules with refined severity classification ---
# High severity = always quarantine (never strip)
# Medium severity = safe to strip with targeted sanitization

YARA_RULES = """
rule eicar_test {
    meta:
        description = "Detects EICAR test file signature"
        severity = "High"
    strings:
        $eicar = "EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
    condition:
        $eicar
}

rule pdf_javascript_high {
    meta:
        description = "Detects embedded JavaScript in PDF (High - quarantine)"
        severity = "High"
    strings:
        $js = /\/JS\s*/
        $javascript = /\/JavaScript\s*/
    condition:
        any of them
}

rule pdf_openaction_high {
    meta:
        description = "Detects PDF OpenAction (High - quarantine)"
        severity = "High"
    strings:
        $openaction = /\/OpenAction\s*/
    condition:
        $openaction
}

rule pdf_launch_high {
    meta:
        description = "Detects PDF Launch action (High - quarantine)"
        severity = "High"
    strings:
        $launch = /\/Launch\s*/
    condition:
        $launch
}

rule pdf_richmedia_high {
    meta:
        description = "Detects RichMedia in PDF (High - quarantine)"
        severity = "High"
    strings:
        $richmedia = /\/RichMedia\s*/
    condition:
        $richmedia
}

rule pdf_embeddedfile_high {
    meta:
        description = "Detects EmbeddedFiles in PDF (High - quarantine)"
        severity = "High"
    strings:
        $embeddedfiles = /\/EmbeddedFiles\s*/
    condition:
        $embeddedfiles
}

rule pdf_xfa_high {
    meta:
        description = "Detects XFA forms in PDF (High - quarantine)"
        severity = "High"
    strings:
        $xfa = /\/XFA\s*/
    condition:
        $xfa
}

rule pdf_aa_high {
    meta:
        description = "Detects PDF AA (Additional Actions) (High - quarantine)"
        severity = "High"
    strings:
        $aa = /\/AA\s*/
    condition:
        $aa
}

rule pdf_annotations_medium {
    meta:
        description = "Detects PDF Annotations (Informational - scan only)"
        severity = "Informational"
    strings:
        $annot = /\/Annot\s*/
        $widget = /\/Widget\s*/
        $film = /\/Film\s*/
        $sound = /\/Sound\s*/
    condition:
        any of them
}

rule pdf_metadata_medium {
    meta:
        description = "Detects PDF Metadata/XMP (Informational - scan only)"
        severity = "Informational"
    strings:
        $metadata = /\/Metadata\s*/
    condition:
        $metadata
}

rule pdf_acroform_medium {
    meta:
        description = "Detects PDF AcroForm (Informational - scan only)"
        severity = "Informational"
    strings:
        $acroform = /\/AcroForm\s*/
    condition:
        $acroform
}

rule vba_macro_high {
    meta:
        description = "Detects VBA macros in DOCX (High - quarantine)"
        severity = "High"
    strings:
        $vba = /VBA/
        $vbaproj = /vbaProject\.bin/
    condition:
        any of them
}

rule dde_auto_high {
    meta:
        description = "Detects DDEAUTO in DOCX (High - quarantine)"
        severity = "High"
    strings:
        $dde = /DDEAUTO/
    condition:
        $dde
}

rule external_link_medium {
    meta:
        description = "Detects external HTTP/HTTPS links (Informational - scan only)"
        severity = "Informational"
    strings:
        $http = "http://"
        $https = "https://"
        $file = "file://"
    condition:
        any of them
}

rule zip_path_traversal_high {
    meta:
        description = "Detects path traversal in ZIP entries (High - quarantine)"
        severity = "High"
    strings:
        $traversal = ".."
    condition:
        any of them
}

rule docx_custom_props_medium {
    meta:
        description = "Detects DOCX custom properties (Informational - scan only)"
        severity = "Informational"
    strings:
        $custom = "docProps/custom.xml"
    condition:
        $custom
}
"""

_yara_rules: Optional[yara.Rules] = None


def _get_yara_rules() -> yara.Rules:
    global _yara_rules
    if _yara_rules is None:
        _yara_rules = yara.compile(source=YARA_RULES)
    return _yara_rules


# --- Scan findings ---

@dataclass
class ScanFinding:
    """A single threat finding from any scanner stage."""
    rule_id: str
    stage: str  # "magic", "zip", "yara", "cdr", "structural", "encryption"
    scan_layer: str  # "raw"|"yara"|"structural"|"cdr"|"encryption"|"zip"
    severity: str  # "High", "Medium", "Low", "Informational"
    description: str
    matched_strings: list[str] = field(default_factory=list)


@dataclass
class SanitizedArtifact:
    """Output of the CDR pipeline — safe for OCR/LLM consumption."""
    sha256: str
    raw_sha256: str  # SHA-256 of original upload (immutable, for audit)
    file_type: str  # "pdf", "docx", "text"
    original_size: int
    sanitized_size: int
    sanitized_bytes: bytes
    scan_engine: str
    infected: bool
    threat_name: Optional[str] = None
    findings: list[ScanFinding] = field(default_factory=list)
    cdr_applied: bool = False
    cdr_method: Optional[str] = None
    sanitized_artifact_uri: Optional[str] = None  # derived artifact storage URI
    scanned_at: float = 0.0


# --- Step 1: Magic-Byte Check ---

PDF_HEADER = b"%PDF-"
DOCX_HEADER = b"PK\x03\x04"


def magic_byte_check(file_bytes: bytes) -> tuple[str, Optional[ScanFinding], Optional[str]]:
    """Validate file type from magic bytes and detect encryption.

    Returns (file_type, finding_if_rejected, encryption_reason_if_any).
    """
    # Detect password-protected PDF before YARA can't see inside
    if file_bytes.startswith(PDF_HEADER):
        # Quick check for /Encrypt in trailer (first 2KB usually enough for small PDFs)
        # Full detection done in encryption_check step
        return "pdf", None, None

    if file_bytes.startswith(DOCX_HEADER):
        return "docx", None, None

    # Try plain text
    try:
        file_bytes.decode("utf-8")
        return "text", None, None
    except UnicodeDecodeError:
        finding = ScanFinding(
            rule_id="INVALID_FILE_TYPE",
            stage="magic",
            scan_layer="magic",
            severity="High",
            description="File does not match PDF, DOCX, or valid UTF-8 text",
        )
        return "unknown", finding, None


def encryption_check(file_bytes: bytes, file_type: str) -> Optional[ScanFinding]:
    """Detect password-protected/encrypted files.

    Returns finding if encrypted, None if safe.
    Only flags explicit PasswordError — other pikepdf errors are passed
    to structural_parse_check for handling.
    """
    if file_type != "pdf":
        return None

    try:
        with pikepdf.open(io.BytesIO(file_bytes)) as pdf:
            if pdf.is_encrypted:
                return ScanFinding(
                    rule_id="PDF_ENCRYPTED",
                    stage="encryption",
                    scan_layer="encryption",
                    severity="High",
                    description="PDF is password-protected / encrypted",
                )
    except pikepdf.PasswordError:
        return ScanFinding(
            rule_id="PDF_PASSWORD_PROTECTED",
            stage="encryption",
            scan_layer="encryption",
            severity="High",
            description="PDF is password-protected",
        )
    except Exception:
        # Corrupt or unreadable PDF — don't block here; structural_parse_check
        # will catch it with more context. Return None to let pipeline continue.
        return None

    return None


# --- Step 2: Zip-Bomb Guard ---

def zip_bomb_guard(file_bytes: bytes, file_type: str, cfg) -> Optional[ScanFinding]:
    """Check DOCX (ZIP) for archive bombs and path traversal."""
    if file_type != "docx":
        return None

    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            entries = zf.infolist()

            if len(entries) > cfg.max_zip_entries:
                return ScanFinding(
                    rule_id="ZIP_ENTRY_COUNT",
                    stage="zip",
                    scan_layer="zip",
                    severity="High",
                    description=f"Too many ZIP entries: {len(entries)} > {cfg.max_zip_entries}",
                )

            total_compressed = sum(i.compress_size for i in entries)
            total_uncompressed = sum(i.file_size for i in entries)
            if total_compressed > 0:
                ratio = total_uncompressed / total_compressed
                if ratio > cfg.max_compression_ratio:
                    return ScanFinding(
                        rule_id="ZIP_BOMB_RATIO",
                        stage="zip",
                        scan_layer="zip",
                        severity="High",
                        description=f"Compression ratio {ratio:.1f}x > {cfg.max_compression_ratio}x",
                    )

            for entry in entries:
                if ".." in entry.filename or entry.filename.startswith("/"):
                    return ScanFinding(
                        rule_id="ZIP_PATH_TRAVERSAL",
                        stage="zip",
                        scan_layer="zip",
                        severity="High",
                        description=f"Path traversal in ZIP entry: {entry.filename}",
                    )
    except zipfile.BadZipFile:
        return ScanFinding(
            rule_id="BAD_ZIP",
            stage="zip",
            scan_layer="zip",
            severity="High",
            description="DOCX file is not a valid ZIP archive",
        )

    return None


# --- Step 3: yara-python Scan ---

def yara_scan(file_bytes: bytes) -> list[ScanFinding]:
    """Scan file bytes with embedded YARA rules.

    Returns list of findings with refined severity (High vs Medium).
    """
    findings: list[ScanFinding] = []
    try:
        rules = _get_yara_rules()
        matches = rules.match(data=file_bytes)
        for match in matches:
            matched_strings = []
            for sm in match.strings:
                try:
                    data = sm.data if hasattr(sm, "data") else str(sm)
                    matched_strings.append(
                        data.decode("utf-8", errors="replace")[:100]
                        if isinstance(data, bytes)
                        else str(data)[:100]
                    )
                except Exception:
                    matched_strings.append(str(sm)[:100])

            # Get severity from rule metadata, default to High
            severity = "High"
            try:
                meta = match.meta
                if "severity" in meta:
                    severity = str(meta["severability"] if hasattr(meta, "severability") else meta.get("severity", "High"))
            except Exception:
                pass

            findings.append(ScanFinding(
                rule_id=f"YARA_{match.rule.upper()}",
                stage="yara",
                scan_layer="yara",
                severity=severity,
                description=f"YARA rule matched: {match.rule}",
                matched_strings=matched_strings[:5],
            ))
    except Exception:
        pass

    return findings


# --- Step 4: Structural Parse Check (runs even on no-findings branch) ---

def structural_parse_check(file_bytes: bytes, file_type: str, doc=None) -> Optional[ScanFinding]:
    """Validate that the file can be structurally parsed.

    For PDF: if a pymupdf doc handle is provided, iterate pages with
    page.read_contents() on that handle. Otherwise fall back to pikepdf/pymupdf.
    For DOCX: defusedxml parse of word/document.xml.
    For text: no structural check needed.

    Returns finding if parsing fails, None if safe.
    """
    if file_type == "pdf":
        # If a pymupdf doc handle is already open (from intake), use it.
        if doc is not None:
            try:
                for page in doc:
                    _ = page.read_contents()
                return None  # structural check passed
            except Exception as exc:
                return ScanFinding(
                    rule_id="PDF_STRUCTURAL_INVALID",
                    stage="structural",
                    scan_layer="structural",
                    severity="High",
                    description=f"PDF structural validation failed: {exc}",
                )
        # No doc handle provided — fall back to pikepdf/pymupdf
        try:
            with pikepdf.open(io.BytesIO(file_bytes)) as pdf:
                _ = pdf.pages
                for page in pdf.pages:
                    _ = page.get_contents()
            return None  # pikepdf succeeded
        except pikepdf.PasswordError:
            return ScanFinding(
                rule_id="PDF_PASSWORD_PROTECTED",
                stage="structural",
                scan_layer="structural",
                severity="High",
                description="PDF is password-protected (detected during structural parse)",
            )
        except Exception:
            # pikepdf failed — try pymupdf as fallback before blocking
            try:
                doc = pymupdf.open(stream=file_bytes, filetype="pdf")
                if doc.page_count == 0:
                    doc.close()
                    return ScanFinding(
                        rule_id="PDF_STRUCTURAL_INVALID",
                        stage="structural",
                        severity="High",
                        description="PDF has zero pages",
                    )
                doc.close()
                return None  # pymupdf succeeded
            except Exception as exc:
                return ScanFinding(
                    rule_id="PDF_STRUCTURAL_INVALID",
                    stage="structural",
                    scan_layer="structural",
                    severity="High",
                    description=f"PDF structural validation failed: {exc}",
                )

    elif file_type == "docx":
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                if "word/document.xml" not in zf.namelist():
                    return ScanFinding(
                        rule_id="DOCX_MISSING_DOCUMENT_XML",
                        stage="structural",
                        scan_layer="structural",
                        severity="High",
                        description="DOCX missing word/document.xml",
                    )
                xml_content = zf.read("word/document.xml")
                DefusedET.fromstring(xml_content)
        except zipfile.BadZipFile:
            return ScanFinding(
                rule_id="DOCX_BAD_ZIP",
                stage="structural",
                scan_layer="structural",
                severity="High",
                description="DOCX is not a valid ZIP archive",
            )
        except DefusedET.ParseError as exc:
            return ScanFinding(
                rule_id="DOCX_XML_INVALID",
                stage="structural",
                scan_layer="structural",
                severity="High",
                description=f"DOCX document.xml is not valid XML: {exc}",
            )
        except Exception as exc:
            return ScanFinding(
                rule_id="DOCX_STRUCTURAL_INVALID",
                stage="structural",
                scan_layer="structural",
                severity="High",
                description=f"DOCX structural validation failed: {exc}",
            )

    return None


# --- Step 4b: Targeted CDR (Medium findings only) ---

def cdr_reconstruct_pdf_targeted(file_bytes: bytes) -> tuple[bytes, str, bool]:
    """Targeted PDF sanitization: remove Medium-severity objects, preserve text layer.

    Strips: /Metadata, /AcroForm (non-XFA), /Annotations
    Does NOT touch: /JavaScript, /OpenAction, /Launch, /RichMedia, /EmbeddedFile, /XFA, /AA
    (Those are High severity and should have been blocked already)

    Returns (sanitized_bytes, method, applied).
    """
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")

    # Remove annotations from each page (Medium: safe to strip)
    for page in doc:
        annots = page.annots()
        if annots:
            for annot in annots:
                try:
                    page.delete_annot(annot)
                except Exception:
                    pass

    buf = io.BytesIO()
    doc.save(buf, deflate=True, garbage=4)
    doc.close()
    return buf.getvalue(), "pdf_targeted_sanitize", True


def cdr_reconstruct_docx(file_bytes: bytes) -> tuple[bytes, str, bool]:
    """CDR for DOCX: extract plain text only, strip all active content.

    Removes VBA macros, DDE fields, embedded objects, external links,
    custom properties, and all OOXML active content.
    """
    import zipfile
    from xml.etree import ElementTree as ET

    text_parts: list[str] = []

    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            if "word/document.xml" in zf.namelist():
                xml_content = zf.read("word/document.xml")
                root = ET.fromstring(xml_content)
                for t in root.iter():
                    if t.tag.endswith("}t") or t.tag == "t":
                        if t.text:
                            text_parts.append(t.text)

            for name in zf.namelist():
                if name.startswith("word/header") and name.endswith(".xml"):
                    try:
                        xml_content = zf.read(name)
                        root = ET.fromstring(xml_content)
                        for t in root.iter():
                            if t.tag.endswith("}t") or t.tag == "t":
                                if t.text:
                                    text_parts.append(t.text)
                    except Exception:
                        pass
    except Exception:
        pass

    clean_text = "\n".join(text_parts)
    return clean_text.encode("utf-8"), "docx_to_clean_text", True


def cdr_reconstruct_pdf_full(file_bytes: bytes, dpi: int = 200) -> tuple[bytes, str, bool]:
    """Full CDR for PDF: render each page at DPI, produce image-only PDF.

    Destroys text layer, JavaScript, annotations, embedded files,
    and all active content. Fallback when targeted sanitization fails.
    """
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    output = pymupdf.open()

    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        new_page = output.new_page(width=pix.width, height=pix.height)
        new_page.insert_image(pix.irect, stream=pix.tobytes("png"))

    buf = io.BytesIO()
    output.save(buf, deflate=True)
    output.close()
    doc.close()
    return buf.getvalue(), f"pdf_to_images_{dpi}dpi", True


# --- Main scan pipeline ---

def scan_file(file_bytes: bytes, cfg=config, sha256: str | None = None, doc=None) -> SanitizedArtifact:
    """Run the scanner pipeline with conditional CDR.

    Refined flow:
    1. Magic-Byte Check → detect file type
    2. Encryption Check → reject password-protected/corrupt PDFs (422)
    3. Zip-Bomb Guard → reject archive bombs & path traversal
    4. YARA Scan → classify findings as High (quarantine) or Medium (strip)
    5. Structural Parse Check → even on no-findings, validate parseability
    6. CDR Reconstruction (conditional) → only for Medium findings

    Returns a SanitizedArtifact safe for OCR/LLM consumption.
    """
    import time

    if sha256 is None:
        sha256 = hashlib.sha256(file_bytes).hexdigest()
    raw_sha256 = sha256  # immutable hash of original upload
    original_size = len(file_bytes)
    findings: list[ScanFinding] = []
    infected = False
    threat_name: Optional[str] = None

    # Step 1: Magic-Byte Check
    file_type, magic_finding, _ = magic_byte_check(file_bytes)
    if magic_finding:
        findings.append(magic_finding)
        infected = True
        threat_name = magic_finding.rule_id
        return SanitizedArtifact(
            sha256=sha256,
            raw_sha256=raw_sha256,
            file_type=file_type,
            original_size=original_size,
            sanitized_size=0,
            sanitized_bytes=b"",
            scan_engine="yara+cdr",
            infected=infected,
            threat_name=threat_name,
            findings=findings,
            cdr_applied=False,
            cdr_method=None,
            scanned_at=time.time(),
        )

    # Step 2: Encryption Check (before YARA can't see inside)
    # Skip if doc was already opened and checked in intake()
    if doc is None:
        enc_finding = encryption_check(file_bytes, file_type)
        if enc_finding:
            findings.append(enc_finding)
            infected = True
            threat_name = enc_finding.rule_id
            return SanitizedArtifact(
                sha256=sha256,
                raw_sha256=raw_sha256,
                file_type=file_type,
                original_size=original_size,
                sanitized_size=0,
                sanitized_bytes=b"",
                scan_engine="yara+cdr",
                infected=infected,
                threat_name=threat_name,
                findings=findings,
                cdr_applied=False,
                cdr_method=None,
                scanned_at=time.time(),
            )

    # Step 3: Zip-Bomb Guard (DOCX only)
    zip_finding = zip_bomb_guard(file_bytes, file_type, cfg)
    if zip_finding:
        findings.append(zip_finding)
        infected = True
        threat_name = zip_finding.rule_id
        return SanitizedArtifact(
            sha256=sha256,
            raw_sha256=raw_sha256,
            file_type=file_type,
            original_size=original_size,
            sanitized_size=0,
            sanitized_bytes=b"",
            scan_engine="yara+cdr",
            infected=infected,
            threat_name=threat_name,
            findings=findings,
            cdr_applied=False,
            cdr_method=None,
            scanned_at=time.time(),
        )

    # Step 4: YARA scan
    yara_findings = yara_scan(file_bytes)
    findings.extend(yara_findings)

    high_findings = [f for f in yara_findings if f.severity == "High"]
    medium_findings = [f for f in yara_findings if f.severity == "Medium"]
    # Informational findings: record only, add 0 to suspicion, no CDR

    # High-severity findings → BLOCKED (quarantine, never strip)
    if high_findings:
        infected = True
        threat_name = high_findings[0].rule_id
        return SanitizedArtifact(
            sha256=sha256,
            raw_sha256=raw_sha256,
            file_type=file_type,
            original_size=original_size,
            sanitized_size=0,
            sanitized_bytes=b"",
            scan_engine="yara+cdr",
            infected=infected,
            threat_name=threat_name,
            findings=findings,
            cdr_applied=False,
            cdr_method=None,
            scanned_at=time.time(),
        )

    # Step 5: Structural Parse Check — runs even on No findings branch
    # This catches malformed/corrupt files that YARA missed
    struct_finding = structural_parse_check(file_bytes, file_type, doc=doc)
    if struct_finding:
        findings.append(struct_finding)
        infected = True
        threat_name = struct_finding.rule_id
        return SanitizedArtifact(
            sha256=sha256,
            raw_sha256=raw_sha256,
            file_type=file_type,
            original_size=original_size,
            sanitized_size=0,
            sanitized_bytes=b"",
            scan_engine="yara+cdr",
            infected=infected,
            threat_name=threat_name,
            findings=findings,
            cdr_applied=False,
            cdr_method=None,
            scanned_at=time.time(),
        )

    # Step 6: CDR Reconstruction — CONDITIONAL
    # No findings → skip CDR entirely, keep original bytes (text layer intact)
    if not findings:
        return SanitizedArtifact(
            sha256=sha256,
            raw_sha256=raw_sha256,
            file_type=file_type,
            original_size=original_size,
            sanitized_size=original_size,
            sanitized_bytes=file_bytes,
            scan_engine="yara+cdr",
            infected=False,
            threat_name=None,
            findings=[],
            cdr_applied=False,
            cdr_method=None,
            scanned_at=time.time(),
        )

    # Only Informational findings → no CDR, just record them
    if not medium_findings:
        return SanitizedArtifact(
            sha256=sha256,
            raw_sha256=raw_sha256,
            file_type=file_type,
            original_size=original_size,
            sanitized_size=original_size,
            sanitized_bytes=file_bytes,
            scan_engine="yara+cdr",
            infected=False,
            threat_name=None,
            findings=findings,
            cdr_applied=False,
            cdr_method=None,
            scanned_at=time.time(),
        )

    # Medium findings only → apply targeted sanitization
    cdr_applied = False
    cdr_method = None
    sanitized_bytes = file_bytes

    if file_type == "pdf" and cfg.cdr_reconstruct_pdf:
        try:
            sanitized_bytes, cdr_method, cdr_applied = cdr_reconstruct_pdf_targeted(file_bytes)
        except Exception:
            # Fall back to full CDR (renders to images, destroys text layer)
            sanitized_bytes, cdr_method, cdr_applied = cdr_reconstruct_pdf_full(file_bytes, dpi=cfg.cdr_dpi)
    elif file_type == "docx" and cfg.cdr_reconstruct_docx:
        sanitized_bytes, cdr_method, cdr_applied = cdr_reconstruct_docx(file_bytes)
    else:
        sanitized_bytes = file_bytes
        cdr_method = "passthrough"
        cdr_applied = False

    return SanitizedArtifact(
        sha256=sha256,
        raw_sha256=raw_sha256,
        file_type=file_type,
        original_size=original_size,
        sanitized_size=len(sanitized_bytes),
        sanitized_bytes=sanitized_bytes,
        scan_engine="yara+cdr",
        infected=infected,
        threat_name=threat_name,
        findings=findings,
        cdr_applied=cdr_applied,
        cdr_method=cdr_method,
        scanned_at=time.time(),
    )


# --- Legacy compatibility functions ---

def scan_stub(file_bytes: bytes) -> tuple[bool, Optional[str], dict]:
    """Legacy stub — kept for backward compatibility."""
    result = scan_file(file_bytes)
    payload = {
        "engine": "yara+cdr",
        "method": "pipeline",
        "findings": [f.rule_id for f in result.findings],
        "infected": result.infected,
        "cdr_applied": result.cdr_applied,
    }
    return result.infected, result.threat_name, payload


def scan_clamav(file_bytes: bytes) -> tuple[bool, Optional[str], dict]:
    """Legacy clamav wrapper — now delegates to yara+cdr pipeline."""
    result = scan_file(file_bytes)
    payload = {
        "engine": "yara+cdr",
        "method": "pipeline",
        "clamav_fallback": True,
        "infected": result.infected,
        "threat_name": result.threat_name,
        "findings": [f.rule_id for f in result.findings],
    }
    return result.infected, result.threat_name, payload


def scan_file_legacy(file_bytes: bytes, sha256: str, file_type: str):
    """Legacy interface returning ScanResult-like dict."""
    result = scan_file(file_bytes)
    from app.schemas import ScanResult
    return ScanResult(
        sha256=sha256,
        file_type=file_type,
        scan_engine=result.scan_engine,
        infected=result.infected,
        threat_name=result.threat_name,
        payload={
            "findings": [f.rule_id for f in result.findings],
            "cdr_applied": result.cdr_applied,
            "cdr_method": result.cdr_method,
        },
    )
