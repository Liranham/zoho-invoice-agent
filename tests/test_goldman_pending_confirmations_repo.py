"""Tests for PendingConfirmationRepository."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.pending_confirmations import (
    PendingConfirmation, PendingConfirmationRepository,
)


def test_insert_returns_new_id():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = PendingConfirmationRepository(conn)
    bid = uuid4(); eid = uuid4()
    returned = repo.insert(
        bill_id=bid,
        entity_id=eid,
        prompt="Helium 10 $89 — file to AMZ Expert Global?",
        options=[{"label": "Yes, file", "value": "file"},
                  {"label": "Hold", "value": "hold"}],
    )

    assert returned == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.pending_confirmations" in sql


def test_list_open():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    repo = PendingConfirmationRepository(conn)
    repo.list_open(limit=10)

    sql = str(cur.execute.call_args)
    assert "answered_at IS NULL" in sql


def test_record_answer():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = PendingConfirmationRepository(conn)
    pid = uuid4()

    repo.record_answer(pid, answer="file")

    sql = str(cur.execute.call_args)
    assert "answered_at" in sql
    assert "answer" in sql
