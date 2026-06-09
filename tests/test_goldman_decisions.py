"""Tests for decision_timeline."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from goldman.decisions import decision_timeline


def test_decision_timeline_returns_list_with_entity_slug_joined():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    fid1, fid2 = uuid4(), uuid4()
    eid = uuid4()
    cur.fetchall.return_value = [
        (fid1, "Hire UK accountant for VAT filings", "amzg", eid,
         datetime(2026, 6, 8, tzinfo=timezone.utc), None),
        (fid2, "Defer UK VAT registration until threshold", "amzg", eid,
         datetime(2026, 5, 14, tzinfo=timezone.utc), None),
    ]

    result = decision_timeline(conn=conn, topic="VAT")

    assert len(result) == 2
    assert result[0]["fact"] == "Hire UK accountant for VAT filings"
    assert result[0]["entity_slug"] == "amzg"
    assert result[0]["id"] == fid1
    assert result[0]["supersedes_id"] is None
    assert result[1]["fact"] == "Defer UK VAT registration until threshold"
    sql = str(cur.execute.call_args)
    assert "facts_live" in sql
    assert "kind = 'decision'" in sql or "kind='decision'" in sql
    assert "ORDER BY" in sql.upper()


def test_decision_timeline_returns_empty_when_no_match():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    result = decision_timeline(conn=conn, topic="nothing matches")

    assert result == []


def test_decision_timeline_raises_for_empty_topic():
    conn = MagicMock()

    with pytest.raises(ValueError, match="topic"):
        decision_timeline(conn=conn, topic="   ")
