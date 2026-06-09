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
