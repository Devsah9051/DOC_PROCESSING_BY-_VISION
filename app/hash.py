from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any


DOMAIN_TAGS = {
    "block": "egca/block/v1",
    "clean": "egca/clean/v1",
    "record": "egca/record/v1",
    "norm": "egca/norm/v1",
    "state": "egca/state/v1",
    "log": "egca/log/v1",
    "idem": "egca/idem/v1",
}


def canonical_bytes(obj: Any) -> bytes:
    """Serialize to canonical JSON: sorted keys, UTF-8, no whitespace, NFC."""
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    text = unicodedata.normalize("NFC", text)
    return text.encode("utf-8")


def domain_hash(tag: str, payload: Any) -> str:
    """SHA-256(tag + 0x00 + canonical_bytes(payload))."""
    if tag not in DOMAIN_TAGS.values() and tag not in DOMAIN_TAGS:
        raise ValueError(f"unknown domain tag: {tag}")
    # Resolve short tag name to full domain tag if needed
    full_tag = DOMAIN_TAGS.get(tag, tag)
    prefix = full_tag.encode("utf-8") + b"\x00"
    return hashlib.sha256(prefix + canonical_bytes(payload)).hexdigest()


def block_hash(payload: Any) -> str:
    return domain_hash("block", payload)


def clean_hash(payload: Any) -> str:
    return domain_hash("clean", payload)


def record_hash(payload: Any) -> str:
    return domain_hash("record", payload)


def norm_hash(payload: Any) -> str:
    return domain_hash("norm", payload)


def state_hash(payload: Any) -> str:
    return domain_hash("state", payload)


def log_hash(payload: Any) -> str:
    return domain_hash("log", payload)


def idem_hash(version_id: str, parser_build_id: str) -> str:
    """Idempotency key: SHA-256(egca/idem/v1 + 0x00 + version_id + ":" + parser_build_id)."""
    return domain_hash("idem", f"{version_id}:{parser_build_id}")


def original_sha256(file_bytes: bytes) -> str:
    """Plain SHA-256 of file bytes (no domain tag, per spec 4.1 exception)."""
    return hashlib.sha256(file_bytes).hexdigest()
