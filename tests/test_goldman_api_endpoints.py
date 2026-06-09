"""Tests for the API endpoint handlers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from goldman.api.endpoints import (
    handle_who, handle_recall, handle_remember,
    handle_pending_bills, handle_status,
)


def test_handle_who_returns_summary_list():
    with patch("goldman.api.endpoints.app_conn") as mock_conn, \
         patch("goldman.api.endpoints.build_who_view") as mock_build:
        mock_conn.return_value.__enter__.return_value = MagicMock()
        mock_build.return_value = [
            MagicMock(slug="amzg", legal_name="AMZ Expert Global Limited",
                       jurisdiction="HK", parent_entity_id=None,
                       base_currency="HKD", fiscal_year_end=None,
                       registered_address=None, company_number=None,
                       tax_registrations=[], bank_accounts=[],
                       top_clients=[], top_vendors=[],
                       intercompany_flow={"count": 2, "total": 800.0,
                                          "currency": "USD",
                                          "counterpart": "Specific Edge Outsourcing LLC"},
                       last_tp_doc={
                           "filename": "transfer_pricing_hk_us_v1.md",
                           "source": "knowledge_pack",
                           "pack_version": "v1-2026-06",
                           "uploaded_at": "2026-06-09T00:00:00+00:00",
                       }),
        ]

        code, body = handle_who(query={}, body={})

        assert code == 200
        assert "entities" in body
        assert body["entities"][0]["slug"] == "amzg"
        # Phase 6.4 fields surfaced in serialised JSON:
        ic = body["entities"][0]["intercompany_flow"]
        assert ic["count"] == 2
        assert ic["counterpart"] == "Specific Edge Outsourcing LLC"
        tp = body["entities"][0]["last_tp_doc"]
        assert tp["filename"] == "transfer_pricing_hk_us_v1.md"


def test_handle_recall_returns_results(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    with patch("goldman.api.endpoints.app_conn") as mock_conn, \
         patch("goldman.api.endpoints.EmbeddingClient") as mock_emb, \
         patch("goldman.api.endpoints.hybrid_search") as mock_search:
        mock_conn.return_value.__enter__.return_value = MagicMock()
        mock_emb.return_value.embed_batch.return_value = [[0.1] * 1536]
        mock_search.return_value = [
            MagicMock(source_type="fact", source_id=uuid4(),
                       excerpt="UK VAT registered", score=0.42,
                       entity_id=None, metadata={}),
        ]

        code, body = handle_recall(query={}, body={"question": "VAT?"})

        assert code == 200
        assert "results" in body
        assert body["results"][0]["source_type"] == "fact"


def test_handle_recall_400_without_question():
    code, body = handle_recall(query={}, body={})
    assert code == 400
    assert "question" in body["error"].lower()


def test_handle_remember_returns_fact_id():
    with patch("goldman.api.endpoints.app_conn") as mock_conn, \
         patch("goldman.api.endpoints.FactRepository") as mock_facts, \
         patch("goldman.api.endpoints.EntityRepository") as mock_ents:
        mock_conn.return_value.__enter__.return_value = MagicMock()
        fid = uuid4()
        mock_facts.return_value.upsert.return_value = fid
        mock_ents.return_value.get_by_slug.return_value = MagicMock(id=uuid4())

        code, body = handle_remember(
            query={},
            body={"entity": "amzg", "kind": "decision", "text": "use Wise"},
        )

        assert code == 201
        assert body["fact_id"] == str(fid)


def test_handle_pending_bills_lists_open():
    with patch("goldman.api.endpoints.app_conn") as mock_conn, \
         patch("goldman.api.endpoints.BillRepository") as mock_bills:
        mock_conn.return_value.__enter__.return_value = MagicMock()
        mock_bills.return_value.list_pending_partial_writes.return_value = []

        code, body = handle_pending_bills(query={}, body={})

        assert code == 200
        assert "bills" in body
        assert body["bills"] == []


def test_handle_status_returns_service_health():
    with patch("goldman.api.endpoints.app_conn") as mock_conn:
        cur = MagicMock()
        cur.fetchone.return_value = (5,)
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur

        code, body = handle_status(query={}, body={})

        assert code == 200
        assert body["service"] == "goldman"
        assert "entities" in body
