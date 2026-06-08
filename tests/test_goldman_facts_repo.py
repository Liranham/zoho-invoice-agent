"""Tests for FactRepository (minimal Phase 1 — Phase 2 extends)."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.facts import Fact, FactRepository, normalise_fact


def test_normalise_fact_lowercases_and_strips():
    assert normalise_fact("  Hello World  ") == "hello world"
    assert normalise_fact("FOO\nBAR") == "foo bar"


def test_insert_returns_new_id_and_writes_content_hash():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id, 1)   # (id, seen_count)

    repo = FactRepository(conn)
    eid = uuid4()
    returned = repo.upsert(
        entity_id=eid,
        kind="decision",
        fact="Hire a UK accountant for VAT filings",
    )

    assert returned == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.facts" in sql
    assert "ON CONFLICT" in sql
    params = cur.execute.call_args[0][1]
    expected_hash = hashlib.sha256(
        b"hire a uk accountant for vat filings"
    ).hexdigest()
    assert expected_hash in params


def test_list_live_by_entity():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    fid = uuid4()
    eid = uuid4()
    cur.fetchall.return_value = [
        (fid, eid, "decision", "Hire UK accountant for VAT filings",
         "abc123hash", None, "user_explicit", 1),
    ]

    repo = FactRepository(conn)
    facts = repo.list_live_by_entity(eid)

    assert len(facts) == 1
    assert facts[0].kind == "decision"
    sql = str(cur.execute.call_args)
    assert "facts_live" in sql


def test_list_pending_embedding():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    repo = FactRepository(conn)
    repo.list_pending_embedding(limit=10)

    sql = str(cur.execute.call_args)
    assert "embedding IS NULL" in sql
    assert "LIMIT" in sql


def test_set_embedding():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = FactRepository(conn)
    fid = uuid4()

    repo.set_embedding(fid, [0.1, 0.2, 0.3])

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.facts SET embedding" in sql


def test_find_potential_conflicts_uses_cosine_threshold():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    repo = FactRepository(conn)
    fid = uuid4()

    repo.find_potential_conflicts(fid, similarity_threshold=0.85)

    sql = str(cur.execute.call_args)
    assert "<=>" in sql
    assert "0.15" in sql or "0.85" in sql


def test_mark_conflict_writes_array_on_both_rows():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = FactRepository(conn)
    a = uuid4(); b = uuid4()

    repo.mark_conflict(a, b)

    assert cur.execute.call_count == 2
    sqls = [str(c) for c in cur.execute.call_args_list]
    assert any("conflict_with" in s for s in sqls)
