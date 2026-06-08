"""Idempotency hash for vendor bills."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Optional


def normalise_vendor(name: str) -> str:
    """Lowercase + strip punctuation + collapse whitespace."""
    s = re.sub(r"[^\w\s]", "", name)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def bill_hash(
    *,
    vendor: str,
    invoice_number: Optional[str],
    amount: float,
    invoice_date: Optional[date],
) -> str:
    parts = [
        normalise_vendor(vendor),
        (invoice_number or "").strip(),
        f"{float(amount):.2f}",
        invoice_date.isoformat() if invoice_date else "",
    ]
    blob = "|".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
