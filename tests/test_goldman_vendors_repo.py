"""Tests for VendorRepository."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.vendors import Vendor, VendorRepository


def test_upsert_by_name_inserts_new():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = VendorRepository(conn)
    eid = uuid4()
    returned_id = repo.upsert_by_name(
        entity_id=eid,
        vendor_name="Helium 10",
        category="software",
        typical_amount=89.00,
        typical_currency="USD",
        typical_cadence="monthly",
        email_domain="helium10.com",
    )

    assert returned_id == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.vendors" in sql
    assert "ON CONFLICT (entity_id, vendor_name)" in sql


def test_list_by_entity_returns_vendors():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    vid = uuid4()
    eid = uuid4()
    cur.fetchall.return_value = [
        (vid, eid, None, "Helium 10", "helium10.com", "software",
         89.00, "USD", "monthly", False, None, 0, None),
    ]

    repo = VendorRepository(conn)
    vendors = repo.list_by_entity(eid)

    assert len(vendors) == 1
    assert vendors[0].vendor_name == "Helium 10"
    assert vendors[0].typical_amount == 89.00
    assert vendors[0].always_confirm is False


def test_bump_seen_increments_count_and_updates_timestamp():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = VendorRepository(conn)
    vid = uuid4()

    repo.bump_seen(vid, amount=92.00)

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.vendors" in sql
    assert "seen_count" in sql
    assert "last_seen_at" in sql
