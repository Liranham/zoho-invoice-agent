"""Repository for goldman.bot_sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class BotSession:
    id: UUID
    front_door: str
    chat_id: str
    current_entity: Optional[str]
    session_id: str


_COLS = "id, front_door, chat_id, current_entity, session_id"


def _row(r) -> BotSession:
    return BotSession(
        id=r[0], front_door=r[1], chat_id=r[2],
        current_entity=r[3], session_id=r[4],
    )


class BotSessionRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def get_or_create(
        self, *, front_door: str, chat_id: str,
        default_entity: Optional[str], session_id: str,
    ) -> BotSession:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.bot_sessions "
                f"WHERE front_door = %s AND chat_id = %s",
                (front_door, chat_id),
            )
            row = cur.fetchone()
            if row:
                return _row(row)

            cur.execute(
                f"""
                INSERT INTO goldman.bot_sessions
                    (front_door, chat_id, current_entity, session_id)
                VALUES (%s, %s, %s, %s)
                RETURNING {_COLS}
                """,
                (front_door, chat_id, default_entity, session_id),
            )
            return _row(cur.fetchone())

    def set_current_entity(self, front_door: str, chat_id: str,
                            entity_slug: Optional[str]) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.bot_sessions
                SET current_entity = %s, last_active_at = now()
                WHERE front_door = %s AND chat_id = %s
                """,
                (entity_slug, front_door, chat_id),
            )

    def touch(self, front_door: str, chat_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.bot_sessions
                SET last_active_at = now()
                WHERE front_door = %s AND chat_id = %s
                """,
                (front_door, chat_id),
            )
