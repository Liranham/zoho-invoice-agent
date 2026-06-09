"""
Wise authentication.

Two pieces:
- Personal API token (Bearer) — used on every request.
- RSA private key — used only to sign SCA challenges on "high-risk" endpoints
  (Statements, Activities). Webhooks DO NOT need SCA, so the private key is
  optional for the realtime path.
"""

from __future__ import annotations

import base64
import logging

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

logger = logging.getLogger(__name__)


class WiseAuth:
    def __init__(self, api_token: str, private_key_pem: bytes | None = None):
        if not api_token:
            raise ValueError("Wise API token is required")
        self.api_token = api_token
        self._private_key: RSAPrivateKey | None = None
        if private_key_pem:
            self._private_key = serialization.load_pem_private_key(
                private_key_pem, password=None
            )
            logger.info("Wise SCA private key loaded")

    @classmethod
    def from_env_b64(cls, api_token: str, private_key_b64: str | None) -> "WiseAuth":
        pem = base64.b64decode(private_key_b64) if private_key_b64 else None
        return cls(api_token, pem)

    def auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_token}"}

    def sign_ott(self, one_time_token: str) -> str:
        """Sign a Wise SCA one-time-token with the private key.

        Returns base64-encoded RSA-SHA256 signature suitable for the X-Signature
        request header.
        """
        if not self._private_key:
            raise RuntimeError(
                "Wise private key not configured — set WISE_PRIVATE_KEY_B64 to use SCA endpoints"
            )
        signature = self._private_key.sign(
            one_time_token.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("ascii")

    @property
    def has_private_key(self) -> bool:
        return self._private_key is not None
