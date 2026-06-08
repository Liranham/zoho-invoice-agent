"""Tests for BillRepository."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from goldman_db.bills import Bill, BillRepository, DuplicateBillError


def test_insert_returns_new_id():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = BillRepository(conn)
    eid = uuid4()
    returned = repo.insert(
        entity_id=eid,
        vendor_name_at_intake="Helium 10",
        amount=89.00,
        currency="USD",
        idempotency_hash="abc123",
        invoice_number="C0C-001",
        invoice_date=date(2026, 6, 1),
        original_filename="helium10.pdf",
    )

    assert returned == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.bills" in sql


def test_insert_raises_duplicate_when_hash_conflict():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    import psycopg
    cur.execute.side_effect = psycopg.errors.UniqueViolation("duplicate")

    repo = BillRepository(conn)
    with pytest.raises(DuplicateBillError):
        repo.insert(
            entity_id=uuid4(),
            vendor_name_at_intake="x",
            amount=1,
            currency="USD",
            idempotency_hash="dup",
        )


def test_get_by_idempotency_hash():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    bid = uuid4(); eid = uuid4()
    cur.fetchone.return_value = (
        bid, eid, None, "Helium 10", "C0C-001", date(2026, 6, 1),
        89.00, "USD", None, [], None, "abc123", "helium10.pdf",
        False, None, False, None, None, False, None,
        False, False, None, "pending", None, None,
    )

    repo = BillRepository(conn)
    bill = repo.get_by_idempotency_hash("abc123")

    assert bill is not None
    assert bill.idempotency_hash == "abc123"


def test_mark_storage_done():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = BillRepository(conn)
    bid = uuid4()

    repo.mark_storage_done(bid, storage_path="amzg/2026/06/x.pdf")

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.bills" in sql
    assert "in_storage" in sql


def test_mark_drive_done():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = BillRepository(conn)
    bid = uuid4()

    repo.mark_drive_done(bid, drive_file_id="fid_xyz", drive_url="https://drive...")

    sql = str(cur.execute.call_args)
    assert "in_drive" in sql
    assert "drive_file_id" in sql


def test_mark_zoho_done():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = BillRepository(conn)
    bid = uuid4()

    repo.mark_zoho_done(bid, zoho_expense_id="E-1042")

    sql = str(cur.execute.call_args)
    assert "in_zoho" in sql
    assert "zoho_expense_id" in sql


def test_record_failure_sets_last_error_and_status():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = BillRepository(conn)
    bid = uuid4()

    repo.record_failure(bid, error="Zoho 500")

    sql = str(cur.execute.call_args)
    assert "last_error" in sql
    assert "status" in sql


def test_list_pending_partial_writes():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    repo = BillRepository(conn)
    repo.list_pending_partial_writes(limit=20)

    sql = str(cur.execute.call_args)
    assert "status" in sql
    assert "partial" in sql or "pending" in sql
