"""Tests for the onboarding coverage check."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

from goldman.onboarding.coverage import Gap, missing_facts


def test_missing_facts_flags_no_tax_registration():
    eid = uuid4()
    entity = MagicMock()
    entity.id = eid
    entity.slug = "amzg"
    entity.legal_name = "AMZ Expert Global Limited"
    entity.jurisdiction = "HK"

    tax_repo = MagicMock()
    tax_repo.list_live.return_value = []
    bank_repo = MagicMock()
    bank_repo.list_by_entity.return_value = [MagicMock()]   # has bank account

    entity.fiscal_year_end = "03-31"
    entity.registered_address = "Suite 100"
    entity.incorporation_date = date(2024, 1, 1)
    entity.company_number = "HK-12345"

    gaps = missing_facts(entity, tax_repo=tax_repo, bank_repo=bank_repo)

    kinds = {g.kind for g in gaps}
    assert "tax_registration_primary" in kinds


def test_missing_facts_flags_no_bank_account():
    entity = MagicMock()
    entity.id = uuid4()
    entity.slug = "amzg"
    entity.legal_name = "AMZ Expert Global Limited"
    entity.jurisdiction = "HK"
    entity.fiscal_year_end = "03-31"
    entity.registered_address = "Suite 100"
    entity.company_number = "HK-12345"
    entity.incorporation_date = date(2024, 1, 1)

    tax_repo = MagicMock()
    tax_repo.list_live.return_value = [MagicMock(tax_type="profits_tax", jurisdiction="HK")]
    bank_repo = MagicMock()
    bank_repo.list_by_entity.return_value = []

    gaps = missing_facts(entity, tax_repo=tax_repo, bank_repo=bank_repo)

    kinds = {g.kind for g in gaps}
    assert "bank_account" in kinds


def test_missing_facts_flags_missing_metadata_fields():
    entity = MagicMock()
    entity.id = uuid4()
    entity.slug = "amzg"
    entity.legal_name = "AMZ Expert Global Limited"
    entity.jurisdiction = "HK"
    entity.fiscal_year_end = None        # missing
    entity.registered_address = None     # missing
    entity.company_number = "HK-12345"
    entity.incorporation_date = date(2024, 1, 1)

    tax_repo = MagicMock()
    tax_repo.list_live.return_value = [MagicMock()]
    bank_repo = MagicMock()
    bank_repo.list_by_entity.return_value = [MagicMock()]

    gaps = missing_facts(entity, tax_repo=tax_repo, bank_repo=bank_repo)
    kinds = {g.kind for g in gaps}
    assert "fiscal_year_end" in kinds
    assert "registered_address" in kinds


def test_missing_facts_returns_empty_when_complete():
    entity = MagicMock()
    entity.id = uuid4()
    entity.slug = "amzg"
    entity.legal_name = "AMZ Expert Global Limited"
    entity.jurisdiction = "HK"
    entity.fiscal_year_end = "03-31"
    entity.registered_address = "Suite 100, HK"
    entity.company_number = "HK-12345"
    entity.incorporation_date = date(2024, 1, 1)

    tax_repo = MagicMock()
    tax_repo.list_live.return_value = [MagicMock()]
    bank_repo = MagicMock()
    bank_repo.list_by_entity.return_value = [MagicMock()]

    gaps = missing_facts(entity, tax_repo=tax_repo, bank_repo=bank_repo)
    assert gaps == []
