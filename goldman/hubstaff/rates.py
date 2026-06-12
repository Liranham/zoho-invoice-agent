"""Per-contractor pay rate repository.

Stores the hourly rate Liran sets for each Hubstaff user. Goldman uses it
when computing payroll because the public Hubstaff API doesn't expose
pay rates on the standard read scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class MemberRate:
    hubstaff_user_id: int
    full_name: str
    rate_amount: Decimal
    rate_currency: str
    rate_unit: str         # 'hour', 'day', 'month', 'week'


class MemberRateRepository:
    def __init__(self, conn):
        self.conn = conn

    def list_for_entity(self, entity_id) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT hubstaff_user_id, full_name, rate_amount,
                       rate_currency, rate_unit
                FROM goldman.hubstaff_member_rates
                WHERE entity_id = %s
                ORDER BY full_name
                """,
                (entity_id,),
            )
            rows = cur.fetchall()
        return [
            MemberRate(
                hubstaff_user_id=r[0], full_name=r[1],
                rate_amount=Decimal(r[2]), rate_currency=r[3], rate_unit=r[4],
            )
            for r in rows
        ]

    def get(self, entity_id, hubstaff_user_id) -> Optional[MemberRate]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT hubstaff_user_id, full_name, rate_amount,
                       rate_currency, rate_unit
                FROM goldman.hubstaff_member_rates
                WHERE entity_id = %s AND hubstaff_user_id = %s
                """,
                (entity_id, hubstaff_user_id),
            )
            row = cur.fetchone()
        if not row:
            return None
        return MemberRate(
            hubstaff_user_id=row[0], full_name=row[1],
            rate_amount=Decimal(row[2]), rate_currency=row[3], rate_unit=row[4],
        )

    def upsert(self, *, entity_id, hubstaff_user_id: int,
                full_name: str, rate_amount, rate_currency: str = "USD",
                rate_unit: str = "hour", notes: str = "") -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.hubstaff_member_rates
                  (entity_id, hubstaff_user_id, full_name,
                   rate_amount, rate_currency, rate_unit, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (entity_id, hubstaff_user_id) DO UPDATE
                  SET full_name     = EXCLUDED.full_name,
                      rate_amount   = EXCLUDED.rate_amount,
                      rate_currency = EXCLUDED.rate_currency,
                      rate_unit     = EXCLUDED.rate_unit,
                      notes         = EXCLUDED.notes,
                      updated_at    = now()
                """,
                (entity_id, hubstaff_user_id, full_name,
                 rate_amount, rate_currency, rate_unit, notes),
            )
