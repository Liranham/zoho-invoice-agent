"""Tests for DocumentRepository + DocumentChunkRepository."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.documents import (
    Document, DocumentChunk,
    DocumentRepository, DocumentChunkRepository,
)


def test_document_insert_returns_id():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = DocumentRepository(conn)
    eid = uuid4()
    returned = repo.insert(
        entity_id=eid,
        filename="UK_VAT_Strategy_v2.pdf",
        mime_type="application/pdf",
        source="uploaded",
        original_storage_path="documents/amzg/2026/abc-uk_vat.pdf",
    )

    assert returned == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.documents" in sql


def test_document_set_summary_updates_row():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = DocumentRepository(conn)
    did = uuid4()

    repo.set_summary(did, "Two-page advisor letter on UK VAT.")

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.documents" in sql
    assert "summary" in sql


def test_chunk_insert_returns_id():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = DocumentChunkRepository(conn)
    did = uuid4()

    returned = repo.insert(
        document_id=did,
        chunk_index=0,
        text="The advisor flagged the Texas economic-nexus threshold at $500k.",
    )

    assert returned == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.document_chunks" in sql


def test_chunk_list_pending_embedding():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    repo = DocumentChunkRepository(conn)
    repo.list_pending_embedding(limit=20)

    sql = str(cur.execute.call_args)
    assert "embedding IS NULL" in sql


def test_chunk_set_embedding():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = DocumentChunkRepository(conn)
    cid = uuid4()

    repo.set_embedding(cid, [0.1] * 3)

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.document_chunks SET embedding" in sql


def test_document_list_by_entity():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    did = uuid4(); eid = uuid4()
    cur.fetchall.return_value = [
        (did, eid, "letter.pdf", "application/pdf", "uploaded",
         "documents/amzg/2026/letter.pdf", "Summary text", None),
    ]

    repo = DocumentRepository(conn)
    docs = repo.list_by_entity(eid)

    assert len(docs) == 1
    assert docs[0].filename == "letter.pdf"
