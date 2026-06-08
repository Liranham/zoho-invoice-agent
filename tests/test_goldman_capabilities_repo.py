"""Tests for CapabilityRepository."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.capabilities import Capability, CapabilityRepository


def test_list_active_filters_by_is_active():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cap_id = uuid4()
    cur.fetchall.return_value = [
        (cap_id, "recall", "Hybrid retrieval.",
         "tool", {"phase": 2}, True),
    ]

    repo = CapabilityRepository(conn)
    caps = repo.list_active()

    assert len(caps) == 1
    assert caps[0].name == "recall"
    sql = str(cur.execute.call_args)
    assert "is_active = true" in sql.lower() or "is_active = TRUE" in sql


def test_get_by_name_returns_capability():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cap_id = uuid4()
    cur.fetchone.return_value = (cap_id, "recall", "Hybrid retrieval.",
                                  "tool", {"phase": 2}, True)

    repo = CapabilityRepository(conn)
    cap = repo.get_by_name("recall")

    assert cap is not None
    assert cap.kind == "tool"


def test_list_by_kind():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    repo = CapabilityRepository(conn)
    repo.list_by_kind("jurisdiction")

    sql = str(cur.execute.call_args)
    assert "kind = %s" in sql
