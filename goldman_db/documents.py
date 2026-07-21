"""Repositories for goldman.documents + goldman.document_chunks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class Document:
    id: UUID
    entity_id: Optional[UUID]
    filename: str
    mime_type: Optional[str]
    source: str
    original_storage_path: str
    summary: Optional[str]
    uploaded_at: Optional[object]


@dataclass(frozen=True)
class DocumentChunk:
    id: UUID
    document_id: UUID
    chunk_index: int
    text: str
    embedding: Optional[list]


_DOC_COLS = """
    id, entity_id, filename, mime_type, source,
    original_storage_path, summary, uploaded_at
"""
_CHUNK_COLS = "id, document_id, chunk_index, text, embedding"


def _vec_to_str(v) -> str:
    return "[" + ",".join(str(x) for x in v) + "]"


def _doc(r) -> Document:
    return Document(
        id=r[0], entity_id=r[1], filename=r[2], mime_type=r[3],
        source=r[4], original_storage_path=r[5],
        summary=r[6], uploaded_at=r[7] if len(r) > 7 else None,
    )


def _chunk(r) -> DocumentChunk:
    return DocumentChunk(
        id=r[0], document_id=r[1], chunk_index=r[2],
        text=r[3], embedding=r[4] if len(r) > 4 else None,
    )


class DocumentRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def insert(
        self,
        *,
        entity_id: Optional[UUID],
        filename: str,
        mime_type: Optional[str],
        source: str,
        original_storage_path: str,
        pack_topic: Optional[str] = None,
        pack_version: Optional[str] = None,
    ) -> UUID:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.documents
                    (entity_id, filename, mime_type, source,
                     original_storage_path, pack_topic, pack_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (entity_id, filename, mime_type, source,
                 original_storage_path, pack_topic, pack_version),
            )
            return cur.fetchone()[0]

    def set_summary(self, document_id: UUID, summary: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE goldman.documents SET summary = %s WHERE id = %s",
                (summary, document_id),
            )

    def list_by_entity(self, entity_id: UUID) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_DOC_COLS} FROM goldman.documents "
                f"WHERE entity_id = %s ORDER BY uploaded_at DESC",
                (entity_id,),
            )
            return [_doc(r) for r in cur.fetchall()]

    def list_all(self) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_DOC_COLS} FROM goldman.documents "
                f"ORDER BY uploaded_at DESC"
            )
            return [_doc(r) for r in cur.fetchall()]

    def get(self, document_id: UUID) -> Optional[Document]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_DOC_COLS} FROM goldman.documents WHERE id = %s",
                (document_id,),
            )
            row = cur.fetchone()
            return _doc(row) if row else None


class DocumentChunkRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def insert(
        self,
        *,
        document_id: UUID,
        chunk_index: int,
        text: str,
    ) -> UUID:
        # Postgres rejects NUL (0x00) in text columns. Callers should already
        # have stripped them, but one bad chunk must never kill a whole reply.
        text = text.replace("\x00", "") if text else text
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.document_chunks
                    (document_id, chunk_index, text)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (document_id, chunk_index, text),
            )
            return cur.fetchone()[0]

    def list_pending_embedding(self, *, limit: int = 50) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_CHUNK_COLS} FROM goldman.document_chunks "
                f"WHERE embedding IS NULL ORDER BY created_at LIMIT %s",
                (limit,),
            )
            return [_chunk(r) for r in cur.fetchall()]

    def set_embedding(self, chunk_id: UUID, embedding: list) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE goldman.document_chunks SET embedding = %s::vector WHERE id = %s",
                (_vec_to_str(embedding), chunk_id),
            )

    def list_by_document(self, document_id: UUID) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_CHUNK_COLS} FROM goldman.document_chunks "
                f"WHERE document_id = %s ORDER BY chunk_index",
                (document_id,),
            )
            return [_chunk(r) for r in cur.fetchall()]
