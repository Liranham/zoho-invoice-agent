"""Repository for goldman.vendors."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class Vendor:
    id: UUID
    entity_id: UUID
    zoho_contact_id: Optional[str]
    vendor_name: str
    email_domain: Optional[str]
    category: Optional[str]
    typical_amount: Optional[Decimal]
    typical_currency: Optional[str]
    typical_cadence: Optional[str]
    always_confirm: bool
    last_seen_at: Optional[object]   # datetime; psycopg returns datetime.datetime
    seen_count: int
    notes: Optional[str]


_COLS = """
    id, entity_id, zoho_contact_id, vendor_name, email_domain,
    category, typical_amount, typical_currency, typical_cadence,
    always_confirm, last_seen_at, seen_count, notes
"""


def _row(r) -> Vendor:
    return Vendor(
        id=r[0], entity_id=r[1], zoho_contact_id=r[2],
        vendor_name=r[3], email_domain=r[4], category=r[5],
        typical_amount=r[6], typical_currency=r[7],
        typical_cadence=r[8], always_confirm=r[9],
        last_seen_at=r[10], seen_count=r[11], notes=r[12],
    )


class VendorRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def upsert_by_name(
        self,
        *,
        entity_id: UUID,
        vendor_name: str,
        zoho_contact_id: Optional[str] = None,
        email_domain: Optional[str] = None,
        category: Optional[str] = None,
        typical_amount: Optional[float] = None,
        typical_currency: Optional[str] = None,
        typical_cadence: Optional[str] = None,
    ) -> UUID:
        """Insert or update on (entity_id, vendor_name)."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.vendors
                    (entity_id, vendor_name, zoho_contact_id, email_domain,
                     category, typical_amount, typical_currency, typical_cadence)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (entity_id, vendor_name) DO UPDATE
                    SET zoho_contact_id  = COALESCE(EXCLUDED.zoho_contact_id, goldman.vendors.zoho_contact_id),
                        email_domain     = COALESCE(EXCLUDED.email_domain, goldman.vendors.email_domain),
                        category         = COALESCE(EXCLUDED.category, goldman.vendors.category),
                        typical_amount   = COALESCE(EXCLUDED.typical_amount, goldman.vendors.typical_amount),
                        typical_currency = COALESCE(EXCLUDED.typical_currency, goldman.vendors.typical_currency),
                        typical_cadence  = COALESCE(EXCLUDED.typical_cadence, goldman.vendors.typical_cadence)
                RETURNING id
                """,
                (entity_id, vendor_name, zoho_contact_id, email_domain,
                 category, typical_amount, typical_currency, typical_cadence),
            )
            return cur.fetchone()[0]

    def list_by_entity(self, entity_id: UUID) -> list[Vendor]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.vendors "
                f"WHERE entity_id = %s ORDER BY vendor_name",
                (entity_id,),
            )
            return [_row(r) for r in cur.fetchall()]

    def bump_seen(self, vendor_id: UUID, *, amount: Optional[float] = None) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.vendors
                SET seen_count   = seen_count + 1,
                    last_seen_at = now(),
                    typical_amount = COALESCE(typical_amount, %s)
                WHERE id = %s
                """,
                (amount, vendor_id),
            )
