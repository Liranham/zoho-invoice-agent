"""Tests for the Goldman EntityRepository."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from goldman_db.entities import Entity, EntityRepository


def _make_repo(rows):
    """Build an EntityRepository whose cursor returns the given rows."""
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = rows
    cur.fetchone.side_effect = rows if rows else [None]
    repo = EntityRepository(conn)
    return repo, conn, cur


def test_list_all_returns_entities():
    amzg_id = uuid4()
    seo_id = uuid4()
    repo, conn, cur = _make_repo([
        (amzg_id, "amzg", "AMZ Expert Global Limited", "HK", None, "HKD",
         None, "AMZG"),
        (seo_id, "seo", "Specific Edge Outsourcing LLC", "US", amzg_id, "USD",
         None, "SEO"),
    ])

    entities = repo.list_all()

    assert len(entities) == 2
    assert entities[0].slug == "amzg"
    assert entities[0].legal_name == "AMZ Expert Global Limited"
    assert entities[0].parent_entity_id is None
    assert entities[1].slug == "seo"
    assert entities[1].parent_entity_id == amzg_id


def test_get_by_slug_returns_entity():
    amzg_id = uuid4()
    repo, conn, cur = _make_repo([
        (amzg_id, "amzg", "AMZ Expert Global Limited", "HK", None, "HKD",
         None, "AMZG"),
    ])

    entity = repo.get_by_slug("amzg")

    assert entity is not None
    assert entity.slug == "amzg"
    assert entity.zoho_credential_key == "AMZG"


def test_get_by_slug_returns_none_when_missing():
    repo, conn, cur = _make_repo([])
    cur.fetchone.return_value = None

    entity = repo.get_by_slug("nope")

    assert entity is None


def test_get_by_slug_normalises_case():
    """slug lookup is case-insensitive (matches CLI convenience)."""
    amzg_id = uuid4()
    repo, conn, cur = _make_repo([
        (amzg_id, "amzg", "AMZ Expert Global Limited", "HK", None, "HKD",
         None, "AMZG"),
    ])

    entity = repo.get_by_slug("AMZG")

    assert entity is not None
    assert entity.slug == "amzg"
    # Verify the query used the lowercased value
    args = cur.execute.call_args[0]
    assert args[1] == ("amzg",)
