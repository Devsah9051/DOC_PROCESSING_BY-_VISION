from __future__ import annotations

import hashlib
import time
from typing import Optional

from app.config import config
from app.db import cache_get, cache_insert, audit_insert
from app.schemas import Phase1Output, Verdict
from app.seal import seal_fields
from stages.s1_intake import intake, Stage1Error
from stages.s2_verify import verify_pages
from stages.s3_govern import govern
from stages.s4_structure import extract_structure
from stages.s5_normalise import load_taxonomy, normalise_tokens, build_output, write_cache


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def json_dumps(obj) -> bytes:
    import json

    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


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


def _quarantined_output(sha256: str, reason: str, timings_ms: dict) -> Phase1Output:
    verdict = Verdict(
        status="QUARANTINED",
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
    """ENTRY: run_phase1(file_bytes, filename, upload_id)"""
    timings_ms: dict = {}
    versions = {
        "pipeline_version": config.pipeline_version,
        "rules_version": config.rules_version,
    }
    sha256 = hashlib.sha256(file_bytes).hexdigest()

    def record(stage: str, start: float):
        timings_ms[stage] = round((_now_ms() - start), 2)

    # ---- Stage 1: Intake ----
    t0 = _now_ms()
    cached = None
    doc = None
    try:
        ctx = intake(file_bytes, filename, upload_id, config)
        record("stage1_intake", t0)
        if ctx.cache_hit:
            cached = ctx.cached_output
        else:
            doc = ctx.doc
    except Stage1Error as exc:
        record("stage1_intake", t0)
        out = _quarantined_output(sha256, f"intake: {exc}", timings_ms)
        out.report_hash = hashlib.sha256(json_dumps(out)).hexdigest()
        out.signature = seal_fields(sha256, out.report_hash, versions)
        try:
            audit_insert(upload_id, sha256, "QUARANTINED", ["PIPELINE_ERROR"], str(out.model_dump()))
        except Exception:
            pass
        return out
    except Exception as exc:  # fail closed
        record("stage1_intake", t0)
        out = _quarantined_output(sha256, f"intake: {exc}", timings_ms)
        out.report_hash = hashlib.sha256(json_dumps(out)).hexdigest()
        out.signature = seal_fields(sha256, out.report_hash, versions)
        try:
            audit_insert(upload_id, sha256, "QUARANTINED", ["PIPELINE_ERROR"], str(out.model_dump()))
        except Exception:
            pass
        return out

    if cached is not None:
        try:
            return Phase1Output.model_validate(cached)
        except Exception:
            pass  # fall through and rebuild

    # ---- Stage 2: Verify ----
    t0 = _now_ms()
    try:
        page_reports, flags, matched, ocr_only, clean_text, verdict = verify_pages(doc, sha256, config)
        record("stage2_verify", t0)
    except Exception as exc:
        record("stage2_verify", t0)
        out = _quarantined_output(sha256, f"verify: {exc}", timings_ms)
        out.report_hash = hashlib.sha256(json_dumps(out)).hexdigest()
        out.signature = seal_fields(sha256, out.report_hash, versions)
        try:
            audit_insert(upload_id, sha256, "QUARANTINED", ["PIPELINE_ERROR"], str(out.model_dump()))
        except Exception:
            pass
        try:
            doc.close()
        except Exception:
            pass
        return out

    # ---- Stage 3: Govern ----
    t0 = _now_ms()
    try:
        quarantine_payload = None
        if verdict.status == "QUARANTINED":
            import json as _json
            quarantine_payload = _json.dumps({"flags": flags, "verdict": verdict.model_dump()})
        proceed, reason = govern(upload_id, sha256, verdict, quarantine_payload)
        record("stage3_govern", t0)
        if not proceed:
            out = _quarantined_output(sha256, reason, timings_ms)
            out.report_hash = hashlib.sha256(json_dumps(out)).hexdigest()
            out.signature = seal_fields(sha256, out.report_hash, versions)
            try:
                doc.close()
            except Exception:
                pass
            return out
    except Exception as exc:
        record("stage3_govern", t0)
        out = _quarantined_output(sha256, f"govern: {exc}", timings_ms)
        out.report_hash = hashlib.sha256(json_dumps(out)).hexdigest()
        out.signature = seal_fields(sha256, out.report_hash, versions)
        try:
            audit_insert(upload_id, sha256, "QUARANTINED", ["PIPELINE_ERROR"], str(out.model_dump()))
        except Exception:
            pass
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
        output = build_output(
            sections=[s.__dict__ for s in sections],
            tokens=_word_records(matched + ocr_only),
            verdict=verdict,
            versions=versions,
            timings_ms=timings_ms,
            prev_hash=sha256,
        )
        record("stage5_normalise", t0)
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
        out = _quarantined_output(sha256, f"normalise: {exc}", timings_ms)
        out.report_hash = hashlib.sha256(json_dumps(out)).hexdigest()
        out.signature = seal_fields(sha256, out.report_hash, versions)
        try:
            audit_insert(upload_id, sha256, "QUARANTINED", ["PIPELINE_ERROR"], str(out.model_dump()))
        except Exception:
            pass
        try:
            doc.close()
        except Exception:
            pass
        return out
