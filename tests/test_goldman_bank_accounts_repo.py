"""Tests for BankAccountRepository."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.bank_accounts import BankAccount, BankAccountRepository


def test_upsert_by_label_inserts_new():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = BankAccountRepository(conn)
    eid = uuid4()
    returned = repo.upsert_by_label(
        entity_id=eid,
        provider="Wise",
        account_label="Wise USD Operating",
        currency="USD",
        account_identifier="****1234",
    )

    assert returned == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.bank_accounts" in sql


def test_list_by_entity():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    aid = uuid4()
    eid = uuid4()
    cur.fetchall.return_value = [
        (aid, eid, "Wise", "Wise USD", "USD", "****1234",
         None, None, None),
    ]

    repo = BankAccountRepository(conn)
    accts = repo.list_by_entity(eid)

    assert len(accts) == 1
    assert accts[0].provider == "Wise"
    assert accts[0].currency == "USD"


def test_set_balance_updates_row():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = BankAccountRepository(conn)
    aid = uuid4()

    repo.set_balance(aid, 45200.00)

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.bank_accounts" in sql
    assert "last_balance" in sql
