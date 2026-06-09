"""Tests for the goldman who view."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
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

    with patch("goldman.who.intercompany_flow",
               return_value={"count": 0, "total": 0.0, "currency": None}), \
         patch("goldman.who.last_tp_doc", return_value=None):
        view = build_who_view(
            entities_repo=entities_repo,
            tax_repo=tax_repo,
            bank_repo=bank_repo,
            clients_repo=clients_repo,
            vendors_repo=vendors_repo,
            conn=MagicMock(),
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
        intercompany_flow={"count": 0, "total": 0.0, "currency": None,
                           "counterpart": None},
        last_tp_doc=None,
    )

    output = render_who([summary])

    assert "AMZ Expert Global Limited" in output
    assert "amzg" in output
    assert "HK" in output
    assert "03-31" in output


def test_build_who_view_populates_cross_entity_fields_when_counterparts_exist():
    amzg_id = uuid4()
    seo_id = uuid4()
    entities = [
        MagicMock(
            id=amzg_id, slug="amzg",
            legal_name="AMZ Expert Global Limited",
            jurisdiction="HK", parent_entity_id=None,
            base_currency="HKD", fiscal_year_end="03-31",
            registered_address="Suite 100", company_number="HK-12345",
            incorporation_date=date(2024, 1, 1),
        ),
        MagicMock(
            id=seo_id, slug="seo",
            legal_name="Specific Edge Outsourcing LLC",
            jurisdiction="US", parent_entity_id=amzg_id,
            base_currency="USD", fiscal_year_end=None,
            registered_address=None, company_number=None,
            incorporation_date=None,
        ),
    ]
    entities_repo = MagicMock(); entities_repo.list_all.return_value = entities
    tax_repo = MagicMock(); tax_repo.list_live.return_value = []
    bank_repo = MagicMock(); bank_repo.list_by_entity.return_value = []
    clients_repo = MagicMock(); clients_repo.list_by_entity.return_value = []
    vendors_repo = MagicMock(); vendors_repo.list_by_entity.return_value = []
    fake_conn = MagicMock()

    flow_for_a = {"count": 2, "total": 800.0, "currency": "USD"}
    flow_for_b = {"count": 1, "total": 1500.0, "currency": "HKD"}
    tp_doc = {
        "filename": "transfer_pricing_hk_us_v1.md",
        "source": "knowledge_pack",
        "pack_version": "v1-2026-06",
        "uploaded_at": "2026-06-09T00:00:00+00:00",
    }

    with patch("goldman.who.intercompany_flow", side_effect=[flow_for_a, flow_for_b]), \
         patch("goldman.who.last_tp_doc", return_value=tp_doc):
        view = build_who_view(
            entities_repo=entities_repo,
            tax_repo=tax_repo, bank_repo=bank_repo,
            clients_repo=clients_repo, vendors_repo=vendors_repo,
            conn=fake_conn,
        )

    assert len(view) == 2
    # build_who_view augments intercompany_flow with a 'counterpart' key.
    ic_a = view[0].intercompany_flow
    assert ic_a["count"] == 2
    assert ic_a["total"] == 800.0
    assert ic_a["currency"] == "USD"
    assert ic_a["counterpart"] == "Specific Edge Outsourcing LLC"
    assert view[0].last_tp_doc == tp_doc
    ic_b = view[1].intercompany_flow
    assert ic_b["count"] == 1
    assert ic_b["total"] == 1500.0
    assert ic_b["currency"] == "HKD"
    assert ic_b["counterpart"] == "AMZ Expert Global Limited"


def test_render_who_includes_intercompany_and_tp_doc_lines():
    summary = EntitySummary(
        id=uuid4(), slug="amzg",
        legal_name="AMZ Expert Global Limited",
        jurisdiction="HK", parent_entity_id=None,
        base_currency="HKD",
        fiscal_year_end="03-31",
        registered_address="Suite 100",
        company_number="HK-12345",
        incorporation_date=None,
        tax_registrations=[], bank_accounts=[],
        top_clients=[], top_vendors=[],
        intercompany_flow={"count": 3, "total": 1200.0, "currency": "USD",
                           "counterpart": "Specific Edge Outsourcing LLC"},
        last_tp_doc={
            "filename": "transfer_pricing_hk_us_v1.md",
            "source": "knowledge_pack",
            "pack_version": "v1-2026-06",
            "uploaded_at": "2026-06-09T00:00:00+00:00",
        },
    )

    output = render_who([summary])

    assert "Intercompany flow" in output
    assert "Specific Edge Outsourcing LLC" in output
    assert "1200" in output or "1,200" in output
    assert "TP documentation" in output or "TP doc" in output
    assert "transfer_pricing_hk_us_v1.md" in output or "transfer_pricing_hk_us" in output


def test_render_who_handles_no_cross_entity_data():
    summary = EntitySummary(
        id=uuid4(), slug="amzg",
        legal_name="AMZ Expert Global Limited",
        jurisdiction="HK", parent_entity_id=None,
        base_currency="HKD",
        fiscal_year_end="03-31",
        registered_address="Suite 100",
        company_number="HK-12345",
        incorporation_date=None,
        tax_registrations=[], bank_accounts=[],
        top_clients=[], top_vendors=[],
        intercompany_flow={"count": 0, "total": 0.0, "currency": None,
                           "counterpart": None},
        last_tp_doc=None,
    )

    output = render_who([summary])

    assert "Intercompany flow" in output
    assert "TP documentation" in output or "TP doc" in output
    assert "(none)" in output or "no intercompany" in output.lower() or "no TP" in output
