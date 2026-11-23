from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from rapidfuzz import fuzz

from app.config import config
from app.db import cache_insert
from app.seal import seal_fields
from app.schemas import Phase1Output, WordRecord

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


def _canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_output(
    sections: list,
    tokens: List[WordRecord],
    verdict,
    versions: dict,
    timings_ms: dict,
    prev_hash: str,
) -> Phase1Output:
    """6.2 Build Phase1Output, report_hash, seal, write cache."""
    output = Phase1Output(
        sections=sections,
        tokens=tokens,
        verdict=verdict,
        versions=versions,
        timings_ms=timings_ms,
        prev_hash=prev_hash,
        report_hash="",
        signature="",
    )
    dump = output.model_dump(exclude={"report_hash", "signature"})
    report_hash = hashlib.sha256(_canonical_json(dump)).hexdigest()
    signature = seal_fields(prev_hash, report_hash, versions)
    output.report_hash = report_hash
    output.signature = signature
    return output


def write_cache(sha256: str, output: Phase1Output):
    cache_insert(
        sha256,
        output.versions.get("pipeline_version", config.pipeline_version),
        output.versions.get("rules_version", config.rules_version),
        output.model_dump_json(),
    )
