from __future__ import annotations

import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import app.seal as seal


def test_seal_roundtrip(monkeypatch):
    sk = Ed25519PrivateKey.generate()
    raw = sk.private_bytes_raw()
    monkeypatch.setenv("SEAL_KEY", base64.b64encode(raw).decode())
    sig = seal.sign(b"hello world")
    assert seal.verify(b"hello world", sig, base64.b64encode(sk.public_key().public_bytes_raw()).decode()) is True
    assert seal.verify(b"tampered", sig, base64.b64encode(sk.public_key().public_bytes_raw()).decode()) is False


def test_seal_fields_deterministic(monkeypatch):
    sk = Ed25519PrivateKey.generate()
    monkeypatch.setenv("SEAL_KEY", base64.b64encode(sk.private_bytes_raw()).decode())
    s1 = seal.seal_fields("prev", "hash", {"a": "1"})
    s2 = seal.seal_fields("prev", "hash", {"a": "1"})
    assert s1 == s2
