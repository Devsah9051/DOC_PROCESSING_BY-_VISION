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
from app.schemas import Phase1Output, WordRecord, FileState


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
    )
    report_hash = compute_report_hash(
        sections=sections,
        tokens=tokens,
        verdict=verdict,
        versions=versions,
        prev_hash=prev_hash,
        file_state=file_state,
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
) -> str:
    """Compute stage5_root (report_hash) deterministically, excluding timings_ms."""
    dump = {
        "sections": [_dump_item(s) for s in sections],
        "tokens": [_dump_item(t) for t in tokens],
        "verdict": verdict.model_dump(),
        "file_state": file_state.model_dump() if file_state else None,
        "versions": versions,
        "prev_hash": prev_hash,
    }
    return norm_hash(dump)


def write_cache(sha256: str, output: Phase1Output):
    cache_insert(
        sha256,
        output.versions.get("pipeline_version", config.pipeline_version),
        output.versions.get("rules_version", config.rules_version),
        output.model_dump_json(),
    )
