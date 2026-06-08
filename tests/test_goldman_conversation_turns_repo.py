"""Tests for ConversationTurnRepository."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.conversation_turns import (
    ConversationTurn, ConversationTurnRepository,
)


def test_insert_returns_new_id():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = ConversationTurnRepository(conn)
    eid = uuid4()
    returned = repo.insert(
        entity_id=eid,
        session_id="session_abc",
        front_door="cli",
        role="user",
        text="invoice Acme $500",
    )

    assert returned == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.conversation_turns" in sql


def test_list_by_session_returns_turns_in_order():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    t1 = uuid4(); t2 = uuid4(); eid = uuid4()
    cur.fetchall.return_value = [
        (t1, eid, "s1", "cli", "user", "hello", None),
        (t2, eid, "s1", "cli", "assistant", "hi back", None),
    ]

    repo = ConversationTurnRepository(conn)
    turns = repo.list_by_session("s1")

    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[1].role == "assistant"
    sql = str(cur.execute.call_args)
    assert "ORDER BY created_at" in sql


def test_list_pending_embedding_returns_only_null():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    repo = ConversationTurnRepository(conn)
    repo.list_pending_embedding(limit=10)

    sql = str(cur.execute.call_args)
    assert "embedding IS NULL" in sql
    assert "LIMIT" in sql


def test_set_embedding_writes_vector_string():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = ConversationTurnRepository(conn)
    tid = uuid4()

    repo.set_embedding(tid, [0.1, 0.2, 0.3])

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.conversation_turns" in sql
    assert "SET embedding" in sql
    params = cur.execute.call_args[0][1]
    assert "0.1" in params[0] and "0.2" in params[0]
