"""Tests for the goldman who view."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

from goldman.who import EntitySummary, build_who_view, render_who


def test_build_who_view_includes_each_entity():
    amzg_id = uuid4()
    seo_id = uuid4()
    entities = [
        MagicMock(
            id=amzg_id, slug="amzg",
            legal_name="AMZ Expert Global Limited",
            jurisdiction="HK", parent_entity_id=None,
            base_currency="HKD",
            fiscal_year_end="03-31",
            registered_address="Suite 100",
            company_number="HK-12345",
            incorporation_date=date(2024, 1, 1),
        ),
        MagicMock(
            id=seo_id, slug="seo",
            legal_name="Specific Edge Outsourcing LLC",
            jurisdiction="US", parent_entity_id=amzg_id,
            base_currency="USD",
            fiscal_year_end=None,
            registered_address=None,
            company_number=None,
            incorporation_date=None,
        ),
    ]
    entities_repo = MagicMock()
    entities_repo.list_all.return_value = entities

    tax_repo = MagicMock()
    tax_repo.list_live.return_value = []
    bank_repo = MagicMock()
    bank_repo.list_by_entity.return_value = []
    clients_repo = MagicMock()
    clients_repo.list_by_entity.return_value = []
    vendors_repo = MagicMock()
    vendors_repo.list_by_entity.return_value = []

    view = build_who_view(
        entities_repo=entities_repo,
        tax_repo=tax_repo,
        bank_repo=bank_repo,
        clients_repo=clients_repo,
        vendors_repo=vendors_repo,
    )

    assert len(view) == 2
    assert view[0].slug == "amzg"
    assert view[0].parent_entity_id is None
    assert view[1].parent_entity_id == amzg_id


def test_render_who_includes_legal_name_and_jurisdiction():
    summary = EntitySummary(
        id=uuid4(), slug="amzg",
        legal_name="AMZ Expert Global Limited",
        jurisdiction="HK", parent_entity_id=None,
        base_currency="HKD",
        fiscal_year_end="03-31",
        registered_address="Suite 100",
        company_number="HK-12345",
        incorporation_date=None,
        tax_registrations=[],
        bank_accounts=[],
        top_clients=[],
        top_vendors=[],
    )

    output = render_who([summary])

    assert "AMZ Expert Global Limited" in output
    assert "amzg" in output
    assert "HK" in output
    assert "03-31" in output
