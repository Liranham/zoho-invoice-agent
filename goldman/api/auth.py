"""Bearer-token auth check.

Single shared secret in GOLDMAN_API_KEY. Single-user; no rotation in v1.
"""

from __future__ import annotations

import hmac
import os


def is_authorized(headers: dict) -> bool:
    expected = os.getenv("GOLDMAN_API_KEY", "")
    if not expected:
        return False
    raw = headers.get("Authorization") or headers.get("authorization") or ""
    if not raw.startswith("Bearer "):
        return False
    token = raw[len("Bearer "):].strip()
    return hmac.compare_digest(token, expected)
