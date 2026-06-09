"""
Test inbound webhook signature verification.

Generates an ephemeral RSA keypair, signs a body with the private key, and
asserts SignatureVerifier accepts the matching signature and rejects tampered
bodies.
"""

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from wise.signature import SignatureVerifier


def _make_keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key()
    return private, public


def _sign(private_key, body: bytes) -> str:
    sig = private_key.sign(body, padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode("ascii")


def test_verify_accepts_valid_signature():
    private, public = _make_keypair()
    body = b'{"event_type":"swift-in#credit","data":{}}'
    signature = _sign(private, body)

    verifier = SignatureVerifier()
    verifier.add_key_for_testing(public)

    assert verifier.verify(body, signature) is True


def test_verify_rejects_tampered_body():
    private, public = _make_keypair()
    body = b'{"event_type":"swift-in#credit","amount":100}'
    signature = _sign(private, body)

    tampered = b'{"event_type":"swift-in#credit","amount":999999}'

    verifier = SignatureVerifier()
    verifier.add_key_for_testing(public)

    assert verifier.verify(tampered, signature) is False


def test_verify_rejects_empty_signature():
    _, public = _make_keypair()
    verifier = SignatureVerifier()
    verifier.add_key_for_testing(public)
    assert verifier.verify(b"hello", "") is False


def test_verify_rejects_garbage_signature():
    _, public = _make_keypair()
    verifier = SignatureVerifier()
    verifier.add_key_for_testing(public)
    assert verifier.verify(b"hello", "not-base64-!!") is False


def test_verify_accepts_with_one_of_many_keys():
    """Multiple public keys cached; any that matches passes."""
    private_a, public_a = _make_keypair()
    _, public_b = _make_keypair()
    body = b'{"x":1}'
    signature = _sign(private_a, body)

    verifier = SignatureVerifier()
    verifier.add_key_for_testing(public_b)  # wrong key
    verifier.add_key_for_testing(public_a)  # correct key

    assert verifier.verify(body, signature) is True
