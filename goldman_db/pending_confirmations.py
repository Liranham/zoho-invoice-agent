"""Repository for goldman.pending_confirmations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class PendingConfirmation:
    id: UUID
    bill_id: UUID
    entity_id: UUID
    prompt: str
    options: list
    telegram_message_id: Optional[int]
    answered_at: Optional[object]
    answer: Optional[str]


_COLS = """
    id, bill_id, entity_id, prompt, options,
    telegram_message_id, answered_at, answer
"""


def _row(r) -> PendingConfirmation:
    return PendingConfirmation(
        id=r[0], bill_id=r[1], entity_id=r[2],
        prompt=r[3], options=r[4] or [],
        telegram_message_id=r[5], answered_at=r[6], answer=r[7],
    )


class PendingConfirmationRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def insert(
        self,
        *,
        bill_id: UUID,
        entity_id: UUID,
        prompt: str,
        options: list,
    ) -> UUID:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.pending_confirmations
                    (bill_id, entity_id, prompt, options)
                VALUES (%s, %s, %s, %s::jsonb)
                RETURNING id
                """,
                (bill_id, entity_id, prompt, json.dumps(options)),
            )
            return cur.fetchone()[0]

    def list_open(self, *, limit: int = 50) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS} FROM goldman.pending_confirmations
                WHERE answered_at IS NULL
                ORDER BY created_at LIMIT %s
                """,
                (limit,),
            )
            return [_row(r) for r in cur.fetchall()]

    def record_answer(self, confirmation_id: UUID, *, answer: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.pending_confirmations
                SET answered_at = now(), answer = %s
                WHERE id = %s
                """,
                (answer, confirmation_id),
            )

    def attach_telegram_message(
        self, confirmation_id: UUID, *, telegram_message_id: int,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.pending_confirmations
                SET telegram_message_id = %s WHERE id = %s
                """,
                (telegram_message_id, confirmation_id),
            )
