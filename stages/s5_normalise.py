from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import yaml
from rapidfuzz import fuzz

from app.config import config
from app.db import cache_insert
from app.hash import norm_hash, state_hash
from app.seal import seal_fields
from app.schemas import (
    Phase1Output, WordRecord, FileState, StructureResult,
)


TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "config" / "taxonomy.yaml"


def load_taxonomy() -> dict:
    with open(TAXONOMY_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f).get("skills", {})


def _canonicalize(text: str, taxonomy: dict) -> tuple:
    tl = text.lower()
    for canon, info in taxonomy.items():
        if tl == canon.lower():
            return canon, 1.0
        for alias in info.get("aliases", []):
            if tl == alias.lower():
                return canon, 1.0
    best_canon = None
    best_score = 0.0
    for canon, info in taxonomy.items():
        candidates = [canon] + info.get("aliases", [])
        for cand in candidates:
            s = fuzz.ratio(tl, cand.lower())
            if s > best_score:
                best_score = s
                best_canon = canon
    if best_canon and best_score >= 85:
        return best_canon, best_score / 100.0
    return text, best_score / 100.0


def normalise_tokens(tokens: List[WordRecord], taxonomy: dict) -> List[dict]:
    """6.1 Dictionary + rapidfuzz alias => canonical skills. Keep word_ids."""
    out = []
    seen = {}
    for t in tokens:
        if not t.text.strip():
            continue
        canon, conf = _canonicalize(t.text, taxonomy)
        related = taxonomy.get(canon, {}).get("related", []) if canon in taxonomy else []
        key = canon
        if key not in seen:
            seen[key] = {
                "skill": t.text,
                "canonical": canon,
                "confidence": round(conf, 3),
                "related": related,
                "word_ids": [],
            }
        seen[key]["word_ids"].append(t.word_id)
    return list(seen.values())


def _dump_item(item):
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return item


def build_output(
    sections: list,
    tokens: List[WordRecord],
    verdict,
    versions: dict,
    timings_ms: dict,
    prev_hash: str,
    file_state: Optional[FileState] = None,
    structure_result: Optional[StructureResult] = None,
    clean_artifact_sha256: Optional[str] = None,
) -> Phase1Output:
    """6.2 Build Phase1Output with report_hash (stage5_root) and signature."""
    output = Phase1Output(
        sections=sections,
        tokens=tokens,
        verdict=verdict,
        file_state=file_state,
        versions=versions,
        timings_ms=timings_ms,
        prev_hash=prev_hash,
        report_hash="",
        signature="",
        clean_artifact_sha256=clean_artifact_sha256,
    )
    if structure_result:
        output.structure_record_root = structure_result.record_root
        output.structure_pii_ref = structure_result.pii_ref
        output.structure_labels = structure_result.labels
        output.structure_rule_flags = structure_result.rule_flags
        output.structure_manipulation_flags = [
            mf.model_dump() for mf in structure_result.manipulation_flags
        ]
        output.structure_date_intervals = [
            di.model_dump() for di in structure_result.date_intervals
        ]
        output.structure_conservation_ledger = structure_result.conservation_ledger
        output.structure_track = structure_result.track

    report_hash = compute_report_hash(
        sections=sections,
        tokens=tokens,
        verdict=verdict,
        versions=versions,
        prev_hash=prev_hash,
        file_state=file_state,
        structure_result=structure_result,
        clean_artifact_sha256=clean_artifact_sha256,
    )
    output.report_hash = report_hash
    fs_hash = state_hash(file_state.model_dump() if file_state else {})
    output.signature = seal_fields(report_hash, fs_hash, versions)
    return output


def compute_report_hash(
    sections: list,
    tokens: List[WordRecord],
    verdict,
    versions: dict,
    prev_hash: str,
    file_state: Optional[FileState] = None,
    structure_result: Optional[StructureResult] = None,
    clean_artifact_sha256: Optional[str] = None,
) -> str:
    """Compute stage5_root (report_hash) deterministically, excluding timings_ms.

    Includes ALL structure data so the seal attests to every piece of output data:
    structure_record_root, structure_pii_ref, structure_labels, structure_rule_flags,
    structure_manipulation_flags, structure_date_intervals, structure_conservation_ledger,
    structure_track.
    Also includes clean_artifact_sha256 (Stage 2 hash chain root).
    """
    dump = {
        "sections": [_dump_item(s) for s in sections],
        "tokens": [_dump_item(t) for t in tokens],
        "verdict": verdict.model_dump(),
        "file_state": file_state.model_dump() if file_state else None,
        "versions": versions,
        "prev_hash": prev_hash,
        "clean_artifact_sha256": clean_artifact_sha256,
        "structure_record_root": structure_result.record_root if structure_result else None,
        "structure_pii_ref": structure_result.pii_ref if structure_result else None,
        "structure_labels": structure_result.labels if structure_result else [],
        "structure_rule_flags": structure_result.rule_flags if structure_result else [],
        "structure_manipulation_flags": [
            mf.model_dump() if hasattr(mf, "model_dump") else mf
            for mf in structure_result.manipulation_flags
        ]
        if structure_result
        else [],
        "structure_date_intervals": [
            di.model_dump() if hasattr(di, "model_dump") else di
            for di in structure_result.date_intervals
        ]
        if structure_result
        else [],
        "structure_conservation_ledger": (
            structure_result.conservation_ledger if structure_result else []
        ),
        "structure_track": structure_result.track if structure_result else None,
    }
    return norm_hash(dump)


def write_cache(sha256: str, output: Phase1Output):
    cache_insert(
        sha256,
        output.versions.get("pipeline_version", config.pipeline_version),
        output.versions.get("rules_version", config.rules_version),
        output.model_dump_json(),
    )
