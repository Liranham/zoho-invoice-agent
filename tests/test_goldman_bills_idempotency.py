"""Tests for bill_hash."""

from __future__ import annotations

from datetime import date

from goldman.bills.idempotency import bill_hash, normalise_vendor


def test_normalise_vendor_lowercases_and_strips_punctuation():
    assert normalise_vendor("Helium 10 INC.") == "helium 10 inc"
    assert normalise_vendor("  H10\n") == "h10"


def test_bill_hash_is_stable_for_same_inputs():
    h1 = bill_hash(
        vendor="Helium 10",
        invoice_number="C0C-001",
        amount=89.00,
        invoice_date=date(2026, 6, 1),
    )
    h2 = bill_hash(
        vendor="HELIUM 10 INC.",       # different spelling
        invoice_number="C0C-001",
        amount=89.00,
        invoice_date=date(2026, 6, 1),
    )
    # Vendor normalisation makes these different (INC vs no INC). Expected.
    assert h1 != h2

    h3 = bill_hash(
        vendor="Helium 10",
        invoice_number="C0C-001",
        amount=89.00,
        invoice_date=date(2026, 6, 1),
    )
    assert h1 == h3


def test_bill_hash_differs_on_amount():
    h1 = bill_hash(vendor="X", invoice_number="1", amount=10.00,
                   invoice_date=date(2026, 1, 1))
    h2 = bill_hash(vendor="X", invoice_number="1", amount=10.01,
                   invoice_date=date(2026, 1, 1))
    assert h1 != h2
