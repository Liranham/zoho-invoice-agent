"""Tests for BotSessionRepository."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.bot_sessions import BotSession, BotSessionRepository


def test_get_or_create_inserts_when_missing():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.side_effect = [
        None,
        (new_id, "telegram", "7884172049", "amzg", "session_xyz"),
    ]

    repo = BotSessionRepository(conn)
    s = repo.get_or_create(
        front_door="telegram",
        chat_id="7884172049",
        default_entity="amzg",
        session_id="session_xyz",
    )

    assert s.id == new_id
    assert s.current_entity == "amzg"


def test_get_or_create_returns_existing_when_found():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    existing_id = uuid4()
    cur.fetchone.side_effect = [
        (existing_id, "telegram", "7884172049", "seo", "session_old"),
    ]

    repo = BotSessionRepository(conn)
    s = repo.get_or_create(
        front_door="telegram", chat_id="7884172049",
        default_entity="amzg", session_id="session_new",
    )

    assert s.id == existing_id
    assert s.current_entity == "seo"
    insert_calls = [c for c in cur.execute.call_args_list
                    if "INSERT" in str(c)]
    assert len(insert_calls) == 0


def test_set_current_entity():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = BotSessionRepository(conn)

    repo.set_current_entity("telegram", "7884172049", "seo")

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.bot_sessions" in sql
    assert "current_entity" in sql


def test_touch_updates_last_active():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = BotSessionRepository(conn)
    repo.touch("telegram", "7884172049")

    sql = str(cur.execute.call_args)
    assert "last_active_at" in sql
