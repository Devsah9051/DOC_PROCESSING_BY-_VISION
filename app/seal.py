from __future__ import annotations

import base64
import json
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from app.db import seal_key


def _private_key() -> Ed25519PrivateKey:
    raw = base64.b64decode(seal_key())
    return Ed25519PrivateKey.from_private_bytes(raw)


def sign(payload: bytes) -> str:
    """Return base64 Ed25519 signature of payload."""
    sk = _private_key()
    sig = sk.sign(payload)
    return base64.b64encode(sig).decode("ascii")


def verify(payload: bytes, signature_b64: str, public_key_b64: str) -> bool:
    try:
        pk = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        pk.verify(base64.b64decode(signature_b64), payload)
        return True
    except Exception:
        return False


def seal_fields(stage5_root: str, file_state_hash: str, versions: dict) -> str:
    """Sign a deterministic canonical string over stage5_root + file_state_hash + versions.
    
    Per Section 4.2: the seal covers stage5_root and file_state_hash, signed with
    the Ed25519 key, recording a key id for rotation.
    """
    payload = json.dumps(
        {"stage5_root": stage5_root, "file_state_hash": file_state_hash, "versions": versions},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sign(payload)
