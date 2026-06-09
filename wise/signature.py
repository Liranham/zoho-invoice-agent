"""
Verify inbound webhook signatures.

Wise signs every webhook with RSA-SHA256 over the raw request body. The
signature arrives in the `X-Signature-SHA256` header (base64). Wise publishes
the public key at /v1/payments/public-keys; we cache it for the process
lifetime.

If verification fails, the request must be rejected — never process unverified
webhooks.
"""

from __future__ import annotations

import base64
import logging
import threading
from typing import Optional

import requests as req
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

logger = logging.getLogger(__name__)

# Wise serves both legacy and current public keys; we accept either.
PUBLIC_KEYS_URL = "https://api.wise.com/v1/payments/public-keys"


class SignatureVerifier:
    def __init__(self, public_keys_url: str = PUBLIC_KEYS_URL):
        self.url = public_keys_url
        self._keys: list[RSAPublicKey] = []
        self._lock = threading.Lock()

    def _ensure_keys_loaded(self) -> None:
        with self._lock:
            if self._keys:
                return
            resp = req.get(self.url, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
            # Response shape: {"keys": [{"key": "<PEM>"}, ...]} or a flat list.
            entries = payload.get("keys") if isinstance(payload, dict) else payload
            if not entries:
                raise RuntimeError(f"No public keys returned by {self.url}")
            for entry in entries:
                pem = entry.get("key") if isinstance(entry, dict) else entry
                if not pem:
                    continue
                pem_bytes = pem.encode("utf-8") if isinstance(pem, str) else pem
                key = serialization.load_pem_public_key(pem_bytes)
                self._keys.append(key)
            logger.info("Loaded %d Wise webhook public keys", len(self._keys))

    def verify(self, body: bytes, signature_b64: str) -> bool:
        """Verify the request body against the X-Signature-SHA256 header."""
        if not signature_b64:
            return False
        try:
            self._ensure_keys_loaded()
        except Exception as e:
            logger.exception("Failed to load Wise public keys: %s", e)
            return False

        try:
            signature = base64.b64decode(signature_b64)
        except Exception:
            return False

        for key in self._keys:
            try:
                key.verify(signature, body, padding.PKCS1v15(), hashes.SHA256())
                return True
            except InvalidSignature:
                continue
            except Exception as e:
                logger.warning("Unexpected verify error: %s", e)
        return False

    def add_key_for_testing(self, public_key: RSAPublicKey) -> None:
        """Inject a public key (used by tests to avoid network)."""
        with self._lock:
            self._keys.append(public_key)
