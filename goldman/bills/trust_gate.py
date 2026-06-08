"""Trust gate: decide auto-file vs confirm.

Per spec §7.2 — auto-file requires ALL of:
  1. Known vendor (vendors.seen_count >= 3)
  2. Amount within ±15% of vendors.typical_amount
  3. Amount <= $500 absolute
  4. billing_entity matches a known entity
  5. vendors.always_confirm == false
  6. parse_confidence >= 0.7
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


AUTO_AMOUNT_CEILING = 500.0
TYPICAL_BAND_PCT = 0.15
MIN_SEEN_COUNT = 3
MIN_PARSE_CONFIDENCE = 0.7


@dataclass(frozen=True)
class GateDecision:
    auto_file: bool
    reason: str


def decide_gate(
    *,
    parse,
    vendor,                              # Vendor row or None
    known_entity_slug: Optional[str],    # resolved entity slug or None
    bill_already_filed: bool,
) -> GateDecision:
    if bill_already_filed:
        return GateDecision(False, "Bill already filed (duplicate).")

    if parse.parse_confidence < MIN_PARSE_CONFIDENCE:
        return GateDecision(
            False,
            f"Parse confidence {parse.parse_confidence:.2f} below threshold "
            f"{MIN_PARSE_CONFIDENCE}.",
        )

    if not known_entity_slug:
        return GateDecision(False, "Billing entity unclear from the document.")

    if vendor is None:
        return GateDecision(False, "New vendor — never seen before.")

    if vendor.always_confirm:
        return GateDecision(False, "Vendor flagged as always-confirm.")

    if vendor.seen_count < MIN_SEEN_COUNT:
        return GateDecision(
            False,
            f"Vendor seen only {vendor.seen_count}x (need {MIN_SEEN_COUNT}).",
        )

    if parse.amount > AUTO_AMOUNT_CEILING:
        return GateDecision(
            False,
            f"Amount {parse.amount:.2f} above ${AUTO_AMOUNT_CEILING:.0f} ceiling.",
        )

    if vendor.typical_amount:
        typical = float(vendor.typical_amount)
        if typical > 0:
            delta = abs(parse.amount - typical) / typical
            if delta > TYPICAL_BAND_PCT:
                return GateDecision(
                    False,
                    f"Amount {parse.amount:.2f} deviates {delta*100:.0f}% from "
                    f"vendor typical {typical:.2f}.",
                )

    return GateDecision(True, "Within trust gate; auto-filing.")
