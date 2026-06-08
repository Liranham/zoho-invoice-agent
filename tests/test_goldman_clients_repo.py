"""Tests for ClientRepository."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.clients import Client, ClientRepository


def test_upsert_by_zoho_id_inserts_new():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = ClientRepository(conn)
    entity_id = uuid4()
    returned_id = repo.upsert_by_zoho_id(
        entity_id=entity_id,
        zoho_contact_id="zoho_c_123",
        contact_name="Acme Corp",
        company_name="Acme",
        primary_email="ops@acme.com",
    )

    assert returned_id == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.clients" in sql
    assert "ON CONFLICT" in sql


def test_list_by_entity_returns_clients():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cid = uuid4()
    eid = uuid4()
    cur.fetchall.return_value = [
        (cid, eid, "zoho_c_1", "Acme", "Acme Inc",
         "ops@acme.com", "a", None, None),
    ]

    repo = ClientRepository(conn)
    clients = repo.list_by_entity(eid)

    assert len(clients) == 1
    assert clients[0].contact_name == "Acme"
    assert clients[0].tier == "a"


def test_set_tier_updates_row():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = ClientRepository(conn)
    cid = uuid4()

    repo.set_tier(cid, "b")

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.clients" in sql
    assert "tier" in sql
