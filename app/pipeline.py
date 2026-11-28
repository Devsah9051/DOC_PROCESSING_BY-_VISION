from __future__ import annotations

import hashlib
import time
from typing import List, Optional

import pymupdf

from app.config import config
from app.db import cache_get, cache_insert, audit_insert, scan_result_insert_full
from app.hash import block_hash, clean_hash, record_hash, norm_hash, state_hash, idem_hash, original_sha256
from app.log import append_log
from app.schemas import (
    Phase1Output, Verdict, FileState, Finding, Status,
    IntakeOutcome, BlockRecord, SanitizedArtifact, ScanFinding,
)
from app.seal import seal_fields
from stages.s1_intake import intake, Stage1Error
from stages.s2_verify import verify_pages
from stages.s3_govern import govern_pre, govern_post
from stages.s4_structure import extract_structure, StructureResult
from stages.s5_normalise import load_taxonomy, normalise_tokens, build_output, write_cache


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def json_dumps(obj) -> str:
    import json
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _word_records(items) -> list:
    out = []
    for it in items:
        out.append({
            "word_id": it.word_id,
            "page": it.page,
            "bbox": list(it.bbox),
            "text": it.text,
            "source": getattr(it, "source", "text_layer"),
            "visible": bool(getattr(it, "visible", True)),
            "flags": list(getattr(it, "flags", [])),
        })
    return out


def _failed_output(sha256: str, reason: str, timings_ms: dict) -> Phase1Output:
    """Programming errors and unexpected failures → FAILED, never QUARANTINE (Section 6.13, 11)."""
    verdict = Verdict(
        status="FAILED",
        score=10.0,
        rules=["PIPELINE_ERROR"],
        reasons=[reason],
    )
    return Phase1Output(
        sections=[],
        tokens=[],
        verdict=verdict,
        versions={"pipeline_version": config.pipeline_version, "rules_version": config.rules_version},
        timings_ms=timings_ms,
        prev_hash=sha256,
        report_hash="",
        signature="",
    )


def run_phase1(file_bytes: bytes, filename: str, upload_id: str) -> Phase1Output:
    """ENTRY: run_phase1(file_bytes, filename, upload_id)

    Pipeline flow per Section 2:
    Stage 1 Upload → Stage 3 pre-gate → Stage 2 Verify → Stage 3 post-gate → Stage 4 Structure → Stage 5 Normalise → Sealer → Part II
    """
    timings_ms: dict = {}
    versions = {
        "pipeline_version": config.pipeline_version,
        "rules_version": config.rules_version,
    }

    def record(stage: str, start: float):
        timings_ms[stage] = round((_now_ms() - start), 2)

    # ---- Stage 1: Intake ----
    sha256 = original_sha256(file_bytes)
    t0 = _now_ms()
    doc = None
    try:
        ctx = intake(file_bytes, filename, upload_id, config)
        record("stage1_intake", t0)

        if ctx.outcome == "DUPLICATE":
            # Cache hit: return stored result (Section 12.4)
            if ctx.cached_output is not None:
                try:
                    return Phase1Output.model_validate(ctx.cached_output)
                except Exception:
                    pass
            # Cache hit but cached output invalid → REJECTED
            out = _failed_output(sha256, "intake: cache_hit_invalid", timings_ms)
            out.report_hash = hashlib.sha256(json_dumps(out.model_dump()).encode()).hexdigest()
            out.signature = seal_fields(out.report_hash, "", versions)
            try:
                audit_insert(upload_id, sha256, "FAILED", ["CACHE_INVALID"], str(out.model_dump()))
            except Exception:
                pass
            return out

        if ctx.outcome != "READY":
            # Non-READY outcome: return appropriate terminal output
            if ctx.outcome == "BLOCKED":
                # Security issue → QUARANTINE (not a bug). Falls through to
                # the scanner-infected BLOCKED block below for unified handling.
                pass
            else:
                # REJECTED / EXPIRED / FAILED → FAILED (programming or validation error)
                out = _failed_output(sha256, f"intake: {ctx.reason}", timings_ms)
                out.report_hash = hashlib.sha256(json_dumps(out.model_dump()).encode()).hexdigest()
                out.signature = seal_fields(out.report_hash, "", versions)
                try:
                    audit_insert(upload_id, sha256, out.verdict.status, [ctx.reason], str(out.model_dump()))
                except Exception:
                    pass
                return out

        doc = ctx.doc

        # Stage 1 already ran synchronous scan + CDR (Section 5.2).
        # Use the sanitized artifact and scan findings directly.
        sanitized_artifact = ctx.sanitized_artifact
        scan_findings = ctx.scan_findings

        # Non-READY outcome from scanner (infected file → BLOCKED → QUARANTINE)
        # Also catches raw pre-scan blocks (archive bomb, suspicious PDF object)
        # that fell through from the first check above.
        if ctx.outcome == "BLOCKED":
            out = Phase1Output(
                sections=[], tokens=[],
                verdict=Verdict(status="QUARANTINE", score=10.0, rules=["SCAN_INFECTED"], reasons=[ctx.reason]),
                versions=versions, timings_ms=timings_ms, prev_hash=sha256,
                report_hash="", signature="",
            )
            # Persist scan_results row for raw pre-scan blocks AND scanner-infected blocks (Step 5)
            if ctx.scan_findings:
                try:
                    scan_result_insert_full(
                        sha256=sha256,
                        file_type=ctx.file_type,
                        original_size=ctx.size_bytes,
                        sanitized_size=0,
                        scan_engine="raw+yara+cdr",
                        infected=True,
                        threat_name=ctx.reason,
                        sanitized_sha256=(
                            hashlib.sha256(ctx.sanitized_artifact.sanitized_bytes).hexdigest()
                            if ctx.sanitized_artifact and ctx.sanitized_artifact.sanitized_bytes
                            else None
                        ),
                        findings=[{
                            "rule_id": f.rule_id,
                            "stage": f.stage,
                            "scan_layer": f.scan_layer,
                            "severity": f.severity,
                            "description": f.description,
                            "matched_strings": f.matched_strings,
                        } for f in ctx.scan_findings],
                        cdr_applied=False,
                        cdr_method=None,
                    )
                except Exception:
                    pass
            out.report_hash = hashlib.sha256(json_dumps(out.model_dump()).encode()).hexdigest()
            out.signature = seal_fields(out.report_hash, "", versions)
            try:
                audit_insert(upload_id, sha256, "QUARANTINE", ["SCAN_INFECTED"], str(out.model_dump()))
            except Exception:
                pass
            try:
                if doc is not None:
                    doc.close()
            except Exception:
                pass
            return out

        # Conditional CDR: if CDR was applied, reopen document from sanitized bytes.
        # If CDR was not applied, keep the original doc (text layer intact for fast path).
        if sanitized_artifact.cdr_applied and sanitized_artifact.sanitized_bytes:
            try:
                if doc is not None:
                    doc.close()
                doc = pymupdf.open(stream=sanitized_artifact.sanitized_bytes, filetype="pdf")
            except Exception:
                # If reopening fails, fall back to original doc (may still be usable)
                pass
    except Stage1Error as exc:
        record("stage1_intake", t0)
        out = _failed_output(sha256, f"intake: {exc}", timings_ms)
        out.report_hash = hashlib.sha256(json_dumps(out.model_dump()).encode()).hexdigest()
        out.signature = seal_fields(out.report_hash, "", versions)
        try:
            audit_insert(upload_id, sha256, "FAILED", ["PIPELINE_ERROR"], str(out.model_dump()))
        except Exception:
            pass
        return out
    except Exception as exc:  # programming error → FAILED, never QUARANTINE
        record("stage1_intake", t0)
        out = _failed_output(sha256, f"intake: {exc}", timings_ms)
        out.report_hash = hashlib.sha256(json_dumps(out.model_dump()).encode()).hexdigest()
        out.signature = seal_fields(out.report_hash, "", versions)
        try:
            audit_insert(upload_id, sha256, "FAILED", ["PIPELINE_ERROR"], str(out.model_dump()))
        except Exception:
            pass
        return out

    # Non-PDF files accepted by Stage 1: use sanitized text for downstream stages.
    # DOCX → clean text from CDR; text → original bytes.
    # No pymupdf doc → Stage 2 verify is skipped (minimal CLEAN verdict).
    clean_artifact_sha256 = clean_hash([])
    if doc is None:
        clean_text = sanitized_artifact.sanitized_bytes.decode("utf-8", errors="replace") if sanitized_artifact.sanitized_bytes else ""
        # Create word tokens from clean text for Structure/Normalise stages
        # Deterministic pseudo-geometry: sequential bboxes based on word position
        matched: List = []
        word_id = 0
        x = 0.0
        for wtext in clean_text.split():
            width = max(len(wtext) * 6.0, 6.0)  # ~6pt per char, min width 6
            matched.append(type("WordRecord", (), {
                "word_id": f"w{word_id}",
                "page": 1,
                "bbox": [round(x, 2), 0.0, round(x + width, 2), 12.0],
                "text": wtext,
                "source": "text_layer",
                "visible": True,
                "flags": [],
                "size": 12.0,
                "bold": False,
                "color": 0,
                "font": "Helvetica",
                "classification": "VERIFIED",
            })())
            x += width + 6.0  # word width + gap
            word_id += 1
        ocr_only: List = []
        verdict = Verdict(status="CLEAN", score=0.0, rules=[], reasons=["non_pdf_no_verify"])
        block_records = []
        parse_status = "PARSED"
        # Real clean_artifact_sha256 over extracted text blocks (not nested clean_hash)
        block_hashes = [block_hash({"block_id": w.word_id, "page": w.page, "bbox": list(w.bbox), "verdict": w.classification or "UNCORROBORATED_NOT_VISIBLE"}) for w in matched]
        clean_artifact_sha256 = clean_hash(block_hashes) if block_hashes else clean_hash([])
        record("stage2_verify", t0)  # record timing even though skipped
    else:
        # ---- Stage 2: Verify (PDF only) ----
        t0 = _now_ms()
        try:
            page_reports, flags, matched, ocr_only, clean_text, verdict, block_records, parse_status, clean_artifact_sha256 = verify_pages(doc, sha256, config)
            record("stage2_verify", t0)
        except Exception as exc:
            record("stage2_verify", t0)
            out = _failed_output(sha256, f"verify: {exc}", timings_ms)
            out.report_hash = hashlib.sha256(json_dumps(out.model_dump()).encode()).hexdigest()
            out.signature = seal_fields(out.report_hash, "", versions)
            try:
                doc.close()
            except Exception:
                pass
            return out
    try:
        # Convert ScanFinding dataclasses to dicts for govern_pre
        scan_findings_dicts = [
            {
                "rule_id": f.rule_id,
                "stage": f.stage,
                "severity": f.severity,
                "description": f.description,
                "matched_strings": f.matched_strings,
            }
            for f in (ctx.scan_findings or [])
        ]
        t0 = _now_ms()
        pre_result = govern_pre(upload_id, sha256, config, scan_findings_dicts)
        record("stage3_pre_gate", t0)
        if not pre_result["proceed"]:
            out = _failed_output(sha256, pre_result["reason"], timings_ms)
            out.report_hash = hashlib.sha256(json_dumps(out.model_dump()).encode()).hexdigest()
            out.signature = seal_fields(out.report_hash, "", versions)
            try:
                doc.close()
            except Exception:
                pass
            return out
    except Exception as exc:
        record("stage3_pre_gate", t0)
        out = _failed_output(sha256, f"pre_gate: {exc}", timings_ms)
        out.report_hash = hashlib.sha256(json_dumps(out.model_dump()).encode()).hexdigest()
        out.signature = seal_fields(out.report_hash, "", versions)
        try:
            doc.close()
        except Exception:
            pass
        return out

    # ---- Stage 3 post-gate (after Stage 2) ----
    t0 = _now_ms()
    file_state = None
    try:
        quarantine_payload = None
        if verdict.status == "QUARANTINE":
            quarantine_payload = json_dumps({"flags": flags, "verdict": verdict.model_dump()})
        post_result = govern_post(upload_id, sha256, verdict, quarantine_payload,
            scan_findings=[
                {
                    "rule_id": f.rule_id,
                    "stage": f.stage,
                    "severity": f.severity,
                    "description": f.description,
                    "matched_strings": f.matched_strings,
                }
                for f in (ctx.scan_findings or [])
            ],
            cdr_applied=sanitized_artifact.cdr_applied if sanitized_artifact else False,
        )
        record("stage3_post_gate", t0)
        if not post_result["proceed"]:
            # QUARANTINE is a legitimate outcome (Section 11), not a bug
            file_state = post_result.get("file_state")
            out = Phase1Output(
                sections=[],
                tokens=[],
                verdict=Verdict(status="QUARANTINE", score=10.0, rules=list(verdict.rules), reasons=[post_result["reason"]]),
                file_state=file_state,
                versions={"pipeline_version": config.pipeline_version, "rules_version": config.rules_version},
                timings_ms=timings_ms,
                prev_hash=sha256,
                report_hash="",
                signature="",
            )
            out.report_hash = norm_hash(out.model_dump(exclude={"signature", "report_hash", "timings_ms"}))
            _fs = post_result.get("file_state")
            fs_hash = state_hash(_fs.model_dump() if _fs else {})
            out.signature = seal_fields(out.report_hash, fs_hash, versions)
            try:
                doc.close()
            except Exception:
                pass
            return out
        file_state = post_result.get("file_state")
    except Exception as exc:
        record("stage3_post_gate", t0)
        out = _failed_output(sha256, f"post_gate: {exc}", timings_ms)
        out.report_hash = hashlib.sha256(json_dumps(out.model_dump()).encode()).hexdigest()
        out.signature = seal_fields(out.report_hash, "", versions)
        try:
            doc.close()
        except Exception:
            pass
        return out

    # ---- Stage 4: Structure (clean_text only) ----
    t0 = _now_ms()
    structure_result: Optional[StructureResult] = None
    try:
        structure_result = extract_structure(
            clean_text,
            matched + ocr_only,
            track=ctx.track,
            uploaded_at=ctx.uploaded_at,
        )
        record("stage4_structure", t0)
    except Exception as exc:
        record("stage4_structure", t0)
        structure_result = StructureResult(
            sections=[],
            fields=[],
            track=ctx.track,
        )

    sections = structure_result.sections if structure_result else []
    fields = structure_result.fields if structure_result else []

    # ---- Stage 5: Normalise + Seal ----
    t0 = _now_ms()
    try:
        taxonomy = load_taxonomy()
        skills = normalise_tokens(matched + ocr_only, taxonomy)
        record("stage5_normalise", t0)

        output = build_output(
            sections=sections,
            tokens=_word_records(matched + ocr_only),
            verdict=verdict,
            file_state=file_state,
            versions=versions,
            timings_ms=timings_ms,
            prev_hash=sha256,
            structure_result=structure_result,
            clean_artifact_sha256=clean_artifact_sha256,
            raw_sha256=sha256,
            sanitized_sha256=sanitized_artifact.sha256 if sanitized_artifact else None,
        )

        try:
            write_cache(sha256, output)
        except Exception:
            pass
        try:
            doc.close()
        except Exception:
            pass
        return output
    except Exception as exc:
        record("stage5_normalise", t0)
        out = _failed_output(sha256, f"normalise: {exc}", timings_ms)
        out.report_hash = hashlib.sha256(json_dumps(out.model_dump()).encode()).hexdigest()
        out.signature = seal_fields(out.report_hash, "", versions)
        try:
            audit_insert(upload_id, sha256, "FAILED", ["PIPELINE_ERROR"], str(out.model_dump()))
        except Exception:
            pass
        try:
            doc.close()
        except Exception:
            pass
        return out
