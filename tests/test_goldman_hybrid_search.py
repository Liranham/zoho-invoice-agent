"""Tests for the hybrid_search Python wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.hybrid_search import HybridSearchResult, hybrid_search


def test_hybrid_search_calls_rpc_with_args():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []
    eid = uuid4()

    hybrid_search(
        conn,
        query_embedding=[0.0] * 1536,
        query_text="UK VAT",
        entity_id=eid,
        top_n=10,
    )

    sql = str(cur.execute.call_args)
    assert "goldman.hybrid_search" in sql
    params = cur.execute.call_args[0][1]
    assert eid in params
    assert 10 in params


def test_hybrid_search_maps_rows_to_results():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    sid = uuid4()
    cur.fetchall.return_value = [
        ("fact", sid, "UK VAT registered GB123",
         0.42, None, {"kind": "decision"}),
    ]

    results = hybrid_search(
        conn, query_embedding=[0.0] * 1536, query_text="vat", top_n=5,
    )

    assert len(results) == 1
    assert isinstance(results[0], HybridSearchResult)
    assert results[0].source_type == "fact"
    assert results[0].excerpt.startswith("UK VAT")
    assert results[0].score == 0.42
