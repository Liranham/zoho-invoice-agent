"""Repository for goldman.conversation_turns (append-only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class ConversationTurn:
    id: UUID
    entity_id: Optional[UUID]
    session_id: str
    front_door: str
    role: str
    text: str
    embedding: Optional[list]


_COLS = "id, entity_id, session_id, front_door, role, text, embedding"


def _row(r) -> ConversationTurn:
    return ConversationTurn(
        id=r[0], entity_id=r[1], session_id=r[2],
        front_door=r[3], role=r[4], text=r[5], embedding=r[6],
    )


def _vec_to_str(v) -> str:
    """Serialise a float list to pgvector text format ('[0.1,0.2,...]')."""
    return "[" + ",".join(str(x) for x in v) + "]"


class ConversationTurnRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def insert(
        self,
        *,
        entity_id: Optional[UUID],
        session_id: str,
        front_door: str,
        role: str,
        text: str,
    ) -> UUID:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.conversation_turns
                    (entity_id, session_id, front_door, role, text)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (entity_id, session_id, front_door, role, text),
            )
            return cur.fetchone()[0]

    def list_by_session(self, session_id: str) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.conversation_turns "
                f"WHERE session_id = %s ORDER BY created_at",
                (session_id,),
            )
            return [_row(r) for r in cur.fetchall()]

    def list_pending_embedding(self, *, limit: int = 50) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.conversation_turns "
                f"WHERE embedding IS NULL ORDER BY created_at LIMIT %s",
                (limit,),
            )
            return [_row(r) for r in cur.fetchall()]

    def set_embedding(self, turn_id: UUID, embedding: list) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE goldman.conversation_turns SET embedding = %s::vector WHERE id = %s",
                (_vec_to_str(embedding), turn_id),
            )
