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
