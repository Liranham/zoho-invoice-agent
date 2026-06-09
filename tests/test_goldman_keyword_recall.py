"""Tests for goldman.keyword_recall."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from goldman.keyword_recall import keyword_recall


def _conn_with(fact_rows, chunk_rows=None):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    if chunk_rows is None:
        chunk_rows = []
    cur.fetchall.side_effect = [fact_rows, chunk_rows]
    return conn


def test_keyword_recall_ranks_by_match_count():
    fid1, fid2, fid3 = uuid4(), uuid4(), uuid4()
    eid = uuid4()
    now = datetime.now(timezone.utc)
    facts = [
        (fid1, eid, "decision", "Stay disregarded for US LLC tax purposes", now),
        (fid2, eid, "note",     "Wise USD operating account", now),
        (fid3, eid, "decision", "US LLC files Form 1120 pro forma + Form 5472", now),
    ]
    conn = _conn_with(facts)

    results = keyword_recall(conn, query_text="US LLC tax", top_n=5)

    assert len(results) >= 2
    assert "US LLC" in results[0].excerpt or "US LLC" in results[1].excerpt


def test_keyword_recall_returns_recency_fallback_when_no_keyword_match():
    fid = uuid4()
    eid = uuid4()
    now = datetime.now(timezone.utc)
    facts = [(fid, eid, "note", "Pacific Edge Wyoming", now)]
    conn = _conn_with(facts)

    results = keyword_recall(conn, query_text="completely unrelated query xyzzy")

    assert len(results) == 1
    assert results[0].metadata.get("fallback") == "recency"


def test_keyword_recall_returns_empty_when_no_data_and_fallback_off():
    conn = _conn_with([], [])
    results = keyword_recall(conn, query_text="anything", recency_fallback=False)
    assert results == []
