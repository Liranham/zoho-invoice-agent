"""Repository for goldman.facts (minimal Phase 1 — Phase 2 extends)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class Fact:
    id: UUID
    entity_id: Optional[UUID]
    kind: str
    fact: str
    content_hash: str
    supersedes_id: Optional[UUID]
    source: str
    seen_count: int


_COLS = "id, entity_id, kind, fact, content_hash, supersedes_id, source, seen_count"


def _row(r) -> Fact:
    return Fact(
        id=r[0], entity_id=r[1], kind=r[2], fact=r[3],
        content_hash=r[4], supersedes_id=r[5],
        source=r[6], seen_count=r[7],
    )


def normalise_fact(text: str) -> str:
    """Lowercase, collapse whitespace — used to make content_hash robust to
    inconsequential differences."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _content_hash(text: str) -> str:
    return hashlib.sha256(normalise_fact(text).encode("utf-8")).hexdigest()


class FactRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def upsert(
        self,
        *,
        entity_id: Optional[UUID],
        kind: str,
        fact: str,
        source: str = "user_explicit",
    ) -> UUID:
        """Insert; on (entity_id, content_hash) conflict bump seen_count."""
        h = _content_hash(fact)
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.facts
                    (entity_id, kind, fact, content_hash, source)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (entity_id, content_hash) DO UPDATE
                    SET seen_count = goldman.facts.seen_count + 1
                RETURNING id, seen_count
                """,
                (entity_id, kind, fact, h, source),
            )
            row = cur.fetchone()
            return row[0]

    def list_live_by_entity(self, entity_id: UUID) -> list[Fact]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS} FROM goldman.facts_live
                WHERE entity_id = %s
                ORDER BY created_at DESC
                """,
                (entity_id,),
            )
            return [_row(r) for r in cur.fetchall()]
