"""Tests for the onboarding writer."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

from goldman.onboarding.writer import OnboardingWriter, WriteSummary


def _make_writer():
    return OnboardingWriter(
        entities_repo=MagicMock(),
        tax_repo=MagicMock(),
        clients_repo=MagicMock(),
        vendors_repo=MagicMock(),
        bank_repo=MagicMock(),
        facts_repo=MagicMock(),
    )


def test_write_inserts_tax_registrations():
    w = _make_writer()
    eid = uuid4()
    new_id = uuid4()
    w.tax_repo.insert.return_value = new_id

    summary = w.write(
        entity_slug="amzg",
        entity_id=eid,
        extraction={
            "tax_registrations": [{
                "tax_type": "vat",
                "jurisdiction": "GB",
                "registration_number": "GB123456789",
                "effective_from": "2024-03-01",
                "filing_cadence": "quarterly",
            }],
            "bank_accounts": [],
            "vendors": [],
            "clients": [],
            "facts": [],
            "entity_metadata": {},
        },
    )

    w.tax_repo.insert.assert_called_once()
    kwargs = w.tax_repo.insert.call_args.kwargs
    assert kwargs["entity_id"] == eid
    assert kwargs["tax_type"] == "vat"
    assert kwargs["jurisdiction"] == "GB"
    assert kwargs["effective_from"] == date(2024, 3, 1)
    assert summary.tax_registrations_inserted == 1


def test_write_inserts_vendors_and_bank_accounts():
    w = _make_writer()
    eid = uuid4()

    summary = w.write(
        entity_slug="amzg",
        entity_id=eid,
        extraction={
            "tax_registrations": [],
            "bank_accounts": [{
                "provider": "Wise",
                "account_label": "Wise USD Operating",
                "currency": "USD",
            }],
            "vendors": [{
                "vendor_name": "Helium 10",
                "category": "software",
                "typical_amount": 89.00,
                "typical_currency": "USD",
                "typical_cadence": "monthly",
            }],
            "clients": [],
            "facts": [],
            "entity_metadata": {},
        },
    )

    w.bank_repo.upsert_by_label.assert_called_once()
    w.vendors_repo.upsert_by_name.assert_called_once()
    assert summary.bank_accounts_upserted == 1
    assert summary.vendors_upserted == 1


def test_write_updates_entity_metadata():
    w = _make_writer()
    eid = uuid4()

    w.write(
        entity_slug="amzg",
        entity_id=eid,
        extraction={
            "tax_registrations": [],
            "bank_accounts": [],
            "vendors": [],
            "clients": [],
            "facts": [],
            "entity_metadata": {
                "fiscal_year_end": "03-31",
                "registered_address": "Suite 100, HK",
                "company_number": "HK-12345",
            },
        },
    )

    w.entities_repo.update_metadata.assert_called_once_with(
        "amzg",
        fiscal_year_end="03-31",
        registered_address="Suite 100, HK",
        company_number="HK-12345",
        incorporation_date=None,
    )


def test_write_inserts_facts():
    w = _make_writer()
    eid = uuid4()

    summary = w.write(
        entity_slug="amzg",
        entity_id=eid,
        extraction={
            "tax_registrations": [],
            "bank_accounts": [],
            "vendors": [],
            "clients": [],
            "facts": [
                {"kind": "decision", "fact": "Use Wise for FX"},
                {"kind": "note", "fact": "Accountant: Jane Smith"},
            ],
            "entity_metadata": {},
        },
    )

    assert w.facts_repo.upsert.call_count == 2
    assert summary.facts_upserted == 2
