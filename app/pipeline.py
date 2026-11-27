from __future__ import annotations

import hashlib
import time
from typing import Optional

from app.config import config
from app.db import cache_get, cache_insert, audit_insert
from app.hash import original_sha256, block_hash, clean_hash, record_hash, norm_hash, state_hash, idem_hash
from app.log import append_log
from app.schemas import (
    Phase1Output, Verdict, FileState, Finding, Status,
    IntakeOutcome, BlockRecord,
)
from app.seal import seal_fields
from stages.s1_intake import intake, Stage1Error
from stages.s2_verify import verify_pages
from stages.s3_govern import govern_pre, govern_post
from stages.s4_structure import extract_structure
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
    sha256 = original_sha256(file_bytes)

    def record(stage: str, start: float):
        timings_ms[stage] = round((_now_ms() - start), 2)

    # ---- Stage 1: Intake ----
    t0 = _now_ms()
    doc = None
    try:
        ctx = intake(file_bytes, filename, upload_id, config)
        record("stage1_intake", t0)
        if ctx.cache_hit:
            # Cache hit: return stored result (Section 12.4)
            try:
                return Phase1Output.model_validate(ctx.cached_output)
            except Exception:
                pass
        doc = ctx.doc
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

    # ---- Stage 3 pre-gate (before parsing) ----
    t0 = _now_ms()
    try:
        pre_result = govern_pre(upload_id, sha256, config)
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

    # ---- Stage 2: Verify ----
    t0 = _now_ms()
    try:
        page_reports, flags, matched, ocr_only, clean_text, verdict, block_records, parse_status = verify_pages(doc, sha256, config)
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

    # ---- Stage 3 post-gate (after Stage 2) ----
    t0 = _now_ms()
    file_state = None
    try:
        quarantine_payload = None
        if verdict.status == "QUARANTINE":
            quarantine_payload = json_dumps({"flags": flags, "verdict": verdict.model_dump()})
        post_result = govern_post(upload_id, sha256, verdict, quarantine_payload)
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
    try:
        sections, fields = extract_structure(clean_text, matched + ocr_only)
        record("stage4_structure", t0)
    except Exception as exc:
        record("stage4_structure", t0)
        sections, fields = [], []

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
