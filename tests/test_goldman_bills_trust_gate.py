"""Tests for the trust gate."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

from goldman.bills.trust_gate import GateDecision, decide_gate
from goldman.bills.parser import BillParseResult


def _parse(vendor="Helium 10", amount=89.00, currency="USD",
           billing_entity="AMZ Expert Global Limited", confidence=0.95):
    return BillParseResult(
        vendor=vendor, invoice_number="C0C-001", amount=amount,
        currency=currency, invoice_date=date(2026, 6, 1),
        due_date=None, billing_entity=billing_entity,
        line_items=[], tax_amount=None,
        parse_confidence=confidence,
    )


def _vendor(seen=5, typical_amount=89.00, always_confirm=False):
    v = MagicMock()
    v.id = uuid4()
    v.seen_count = seen
    v.typical_amount = typical_amount
    v.typical_currency = "USD"
    v.always_confirm = always_confirm
    return v


def test_auto_when_known_vendor_small_amount_within_band():
    parse = _parse()
    decision = decide_gate(
        parse=parse, vendor=_vendor(), known_entity_slug="amzg",
        bill_already_filed=False,
    )
    assert isinstance(decision, GateDecision)
    assert decision.auto_file is True


def test_confirm_when_amount_above_500():
    parse = _parse(amount=750.00)
    decision = decide_gate(
        parse=parse, vendor=_vendor(typical_amount=750.00),
        known_entity_slug="amzg", bill_already_filed=False,
    )
    assert decision.auto_file is False
    assert "above" in decision.reason.lower() or "ceiling" in decision.reason.lower()


def test_confirm_when_amount_deviates_more_than_15_percent():
    parse = _parse(amount=120.00)
    decision = decide_gate(
        parse=parse, vendor=_vendor(typical_amount=89.00),
        known_entity_slug="amzg", bill_already_filed=False,
    )
    assert decision.auto_file is False
    assert "deviates" in decision.reason.lower() or "typical" in decision.reason.lower()


def test_confirm_when_new_vendor():
    parse = _parse()
    decision = decide_gate(
        parse=parse, vendor=None, known_entity_slug="amzg",
        bill_already_filed=False,
    )
    assert decision.auto_file is False
    assert "vendor" in decision.reason.lower()


def test_confirm_when_billing_entity_unclear():
    parse = _parse(billing_entity=None)
    decision = decide_gate(
        parse=parse, vendor=_vendor(), known_entity_slug=None,
        bill_already_filed=False,
    )
    assert decision.auto_file is False
    assert "entity" in decision.reason.lower()


def test_confirm_when_low_parse_confidence():
    parse = _parse(confidence=0.5)
    decision = decide_gate(
        parse=parse, vendor=_vendor(), known_entity_slug="amzg",
        bill_already_filed=False,
    )
    assert decision.auto_file is False
    assert "confidence" in decision.reason.lower()


def test_confirm_when_vendor_always_confirm_flag_set():
    parse = _parse()
    decision = decide_gate(
        parse=parse, vendor=_vendor(always_confirm=True),
        known_entity_slug="amzg", bill_already_filed=False,
    )
    assert decision.auto_file is False
    assert "confirm" in decision.reason.lower()
