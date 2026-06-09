"""Tests for cross-entity insight primitives."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from goldman.cross_entity import intercompany_flow, last_tp_doc


def test_intercompany_flow_aggregates_count_total_and_currency():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [
        (400.00, "USD"),
        (500.00, "USD"),
        (300.00, "USD"),
    ]

    eid_a = uuid4()
    result = intercompany_flow(
        conn=conn,
        entity_a_id=eid_a,
        entity_b_legal_name="Specific Edge Outsourcing LLC",
        days=30,
    )

    assert result["count"] == 3
    assert result["total"] == 1200.00
    assert result["currency"] == "USD"

    sql = str(cur.execute.call_args)
    assert "goldman.bills" in sql
    assert "vendor_name_at_intake" in sql
    params = cur.execute.call_args[0][1]
    assert eid_a in params


def test_intercompany_flow_mixed_currencies_marks_mixed():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [
        (100.00, "USD"),
        (50.00, "HKD"),
    ]

    result = intercompany_flow(
        conn=conn,
        entity_a_id=uuid4(),
        entity_b_legal_name="X",
        days=30,
    )

    assert result["count"] == 2
    assert result["total"] == 150.00
    assert result["currency"] == "mixed"


def test_intercompany_flow_no_rows_returns_zero_result():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    result = intercompany_flow(
        conn=conn,
        entity_a_id=uuid4(),
        entity_b_legal_name="X",
        days=30,
    )

    assert result == {"count": 0, "total": 0.0, "currency": None}


def test_last_tp_doc_prefers_knowledge_pack():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (
        "transfer_pricing_hk_us_v1.md",
        "knowledge_pack",
        "v1-2026-06",
        datetime(2026, 6, 9, tzinfo=timezone.utc),
    )

    result = last_tp_doc(
        conn=conn,
        entity_a_legal_name="AMZ Expert Global Limited",
        entity_b_legal_name="Specific Edge Outsourcing LLC",
    )

    assert result is not None
    assert result["filename"] == "transfer_pricing_hk_us_v1.md"
    assert result["source"] == "knowledge_pack"
    assert result["pack_version"] == "v1-2026-06"
    assert result["uploaded_at"] == "2026-06-09T00:00:00+00:00"

    sql_first = str(cur.execute.call_args_list[0])
    assert "knowledge_pack" in sql_first
    assert "transfer_pricing_hk_us" in sql_first


def test_last_tp_doc_falls_back_when_no_pack():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [
        None,
        (
            "2025-cpa-letter.pdf",
            "uploaded",
            None,
            datetime(2025, 11, 15, tzinfo=timezone.utc),
        ),
    ]

    result = last_tp_doc(
        conn=conn,
        entity_a_legal_name="AMZ Expert Global Limited",
        entity_b_legal_name="Specific Edge Outsourcing LLC",
    )

    assert result is not None
    assert result["filename"] == "2025-cpa-letter.pdf"
    assert result["source"] == "uploaded"
    assert result["pack_version"] is None

    assert cur.execute.call_count == 2


def test_last_tp_doc_returns_none_when_nothing_found():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [None, None]

    result = last_tp_doc(
        conn=conn,
        entity_a_legal_name="X", entity_b_legal_name="Y",
    )

    assert result is None
