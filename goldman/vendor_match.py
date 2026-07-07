"""Pure name-matching helpers for vendor deduplication — no I/O.

Decides, from a proposed vendor name and an entity's existing Zoho vendor
contacts, whether the name is the same vendor (exact), a plausible
duplicate worth asking about (similar), or clearly new (none). See
docs/superpowers/specs/2026-07-07-vendor-auto-create-dedup-design.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

_FILLER_WORDS = {
    "the", "llc", "inc", "ltd", "co", "corp", "cpa", "group",
    "services", "company", "holdings", "and", "of",
}

# Calibrated against real examples (see design spec): catches typos and
# added legal suffixes (ratio ~0.82-0.89) without flagging generically
# similar-sounding but unrelated firms (ratio ~0.58 for two different
# "...Services..." companies).
_SIMILARITY_THRESHOLD = 0.72

_MAX_CANDIDATES = 3


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    lowered = (name or "").lower()
    stripped = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return re.sub(r"\s+", " ", stripped).strip()


def significant_words(name: str) -> set:
    """Normalized words with common filler (LLC, CPA, Services, ...) stripped."""
    words = normalize_name(name).split()
    return {w for w in words if w not in _FILLER_WORDS and len(w) > 1}


@dataclass
class VendorMatch:
    kind: str  # Literal["exact", "similar", "none"]
    candidates: list = field(default_factory=list)


def match_vendor(name: str, existing: list) -> "VendorMatch":
    """Compare `name` against `existing` (objects with `.contact_name` and
    `.contact_id`). `existing` should already be scoped to one entity's
    vendor-type contacts — this function does no entity filtering itself.
    """
    target_norm = normalize_name(name)
    if not target_norm:
        return VendorMatch(kind="none")

    for contact in existing:
        if normalize_name(contact.contact_name) == target_norm:
            return VendorMatch(kind="exact", candidates=[contact])

    target_words = significant_words(name)
    scored = []
    for contact in existing:
        other_norm = normalize_name(contact.contact_name)
        other_words = significant_words(contact.contact_name)
        shared = bool(target_words & other_words)
        ratio = SequenceMatcher(None, target_norm, other_norm).ratio()
        if shared or ratio >= _SIMILARITY_THRESHOLD:
            # Shared-word matches rank above pure spelling matches; within
            # each group, higher ratio first.
            rank = (0 if shared else 1, -ratio)
            scored.append((rank, contact))

    if not scored:
        return VendorMatch(kind="none")

    scored.sort(key=lambda pair: pair[0])
    return VendorMatch(kind="similar", candidates=[c for _, c in scored[:_MAX_CANDIDATES]])
