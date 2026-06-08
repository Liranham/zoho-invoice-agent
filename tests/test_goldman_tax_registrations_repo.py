"""Tests for TaxRegistrationRepository."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from goldman_db.tax_registrations import TaxRegistration, TaxRegistrationRepository


def test_insert_returns_new_row():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = TaxRegistrationRepository(conn)
    entity_id = uuid4()
    returned_id = repo.insert(
        entity_id=entity_id,
        tax_type="vat",
        jurisdiction="GB",
        registration_number="GB123456789",
        effective_from=date(2024, 3, 1),
        filing_cadence="quarterly",
        source="user_explicit",
    )

    assert returned_id == new_id
    insert_call = cur.execute.call_args
    assert "INSERT INTO goldman.tax_registrations" in str(insert_call)


def test_list_live_for_entity():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    entity_id = uuid4()
    row_id = uuid4()
    cur.fetchall.return_value = [
        (row_id, entity_id, "vat", "GB", "GB123456789",
         date(2024, 3, 1), None, "quarterly", "test notes",
         None, "user_explicit"),
    ]

    repo = TaxRegistrationRepository(conn)
    rows = repo.list_live(entity_id)

    assert len(rows) == 1
    assert rows[0].tax_type == "vat"
    assert rows[0].jurisdiction == "GB"
    assert rows[0].registration_number == "GB123456789"
    select_call = cur.execute.call_args
    assert "tax_registrations_live" in str(select_call)


def test_supersede_inserts_new_row_with_supersedes_id():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = TaxRegistrationRepository(conn)
    prior_id = uuid4()
    entity_id = uuid4()

    returned_id = repo.supersede(
        prior_id=prior_id,
        entity_id=entity_id,
        tax_type="vat",
        jurisdiction="GB",
        registration_number="GB123456789",
        effective_from=date(2024, 3, 1),
        effective_to=date(2026, 9, 15),
        filing_cadence="quarterly",
        source="user_explicit",
    )

    assert returned_id == new_id
    insert_call_args = cur.execute.call_args
    assert "INSERT INTO goldman.tax_registrations" in str(insert_call_args)
    params = insert_call_args[0][1]
    assert prior_id in params
