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

    def list_pending_embedding(self, *, limit: int = 50) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.facts "
                f"WHERE embedding IS NULL ORDER BY created_at LIMIT %s",
                (limit,),
            )
            return [_row(r) for r in cur.fetchall()]

    def set_embedding(self, fact_id, embedding: list) -> None:
        vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE goldman.facts SET embedding = %s::vector WHERE id = %s",
                (vec_str, fact_id),
            )

    def find_potential_conflicts(
        self, fact_id, *, similarity_threshold: float = 0.85, limit: int = 5,
    ) -> list:
        """Return facts whose embeddings are very close to this fact's but
        whose content_hash differs (suggesting contradictory statements about
        the same topic). Caller decides whether to mark_conflict.
        """
        distance_threshold = 1.0 - similarity_threshold
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS} FROM goldman.facts other
                WHERE other.embedding IS NOT NULL
                  AND other.id != %s
                  AND other.content_hash != (
                      SELECT content_hash FROM goldman.facts WHERE id = %s
                  )
                  AND (
                      other.embedding <=> (
                          SELECT embedding FROM goldman.facts WHERE id = %s
                      )
                  ) < {distance_threshold:.3f}
                ORDER BY other.embedding <=> (
                    SELECT embedding FROM goldman.facts WHERE id = %s
                )
                LIMIT %s
                """,
                (fact_id, fact_id, fact_id, fact_id, limit),
            )
            return [_row(r) for r in cur.fetchall()]

    def mark_conflict(self, fact_a, fact_b) -> None:
        """Add each fact's id to the other's conflict_with array. Idempotent."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.facts
                SET conflict_with = ARRAY(SELECT DISTINCT unnest(conflict_with || %s::uuid))
                WHERE id = %s
                """,
                (fact_b, fact_a),
            )
            cur.execute(
                """
                UPDATE goldman.facts
                SET conflict_with = ARRAY(SELECT DISTINCT unnest(conflict_with || %s::uuid))
                WHERE id = %s
                """,
                (fact_a, fact_b),
            )
