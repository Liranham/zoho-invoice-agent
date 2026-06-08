"""Repository for goldman.bank_accounts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class BankAccount:
    id: UUID
    entity_id: UUID
    provider: str
    account_label: str
    currency: str
    account_identifier: Optional[str]
    last_balance: Optional[Decimal]
    last_balance_at: Optional[object]
    notes: Optional[str]


_COLS = """
    id, entity_id, provider, account_label, currency,
    account_identifier, last_balance, last_balance_at, notes
"""


def _row(r) -> BankAccount:
    return BankAccount(
        id=r[0], entity_id=r[1], provider=r[2], account_label=r[3],
        currency=r[4], account_identifier=r[5],
        last_balance=r[6], last_balance_at=r[7], notes=r[8],
    )


class BankAccountRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def upsert_by_label(
        self,
        *,
        entity_id: UUID,
        provider: str,
        account_label: str,
        currency: str,
        account_identifier: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> UUID:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.bank_accounts
                    (entity_id, provider, account_label, currency,
                     account_identifier, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (entity_id, account_label) DO UPDATE
                    SET provider           = EXCLUDED.provider,
                        currency           = EXCLUDED.currency,
                        account_identifier = COALESCE(EXCLUDED.account_identifier,
                                                      goldman.bank_accounts.account_identifier),
                        notes              = COALESCE(EXCLUDED.notes,
                                                      goldman.bank_accounts.notes)
                RETURNING id
                """,
                (entity_id, provider, account_label, currency,
                 account_identifier, notes),
            )
            return cur.fetchone()[0]

    def list_by_entity(self, entity_id: UUID) -> list[BankAccount]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.bank_accounts "
                f"WHERE entity_id = %s ORDER BY provider, account_label",
                (entity_id,),
            )
            return [_row(r) for r in cur.fetchall()]

    def set_balance(self, account_id: UUID, balance: float) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.bank_accounts
                SET last_balance = %s, last_balance_at = now()
                WHERE id = %s
                """,
                (balance, account_id),
            )
