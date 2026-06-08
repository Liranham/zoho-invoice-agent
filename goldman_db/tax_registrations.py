"""Repository for goldman.tax_registrations (append-only)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class TaxRegistration:
    id: UUID
    entity_id: UUID
    tax_type: str
    jurisdiction: str
    registration_number: Optional[str]
    effective_from: Optional[date]
    effective_to: Optional[date]
    filing_cadence: Optional[str]
    notes: Optional[str]
    supersedes_id: Optional[UUID]
    source: str


_COLS = """
    id, entity_id, tax_type, jurisdiction, registration_number,
    effective_from, effective_to, filing_cadence, notes,
    supersedes_id, source
"""


def _row_to_obj(row) -> TaxRegistration:
    return TaxRegistration(
        id=row[0], entity_id=row[1], tax_type=row[2],
        jurisdiction=row[3], registration_number=row[4],
        effective_from=row[5], effective_to=row[6],
        filing_cadence=row[7], notes=row[8],
        supersedes_id=row[9], source=row[10],
    )


class TaxRegistrationRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def insert(
        self,
        *,
        entity_id: UUID,
        tax_type: str,
        jurisdiction: str,
        registration_number: Optional[str] = None,
        effective_from: Optional[date] = None,
        effective_to: Optional[date] = None,
        filing_cadence: Optional[str] = None,
        notes: Optional[str] = None,
        source: str = "user_explicit",
    ) -> UUID:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.tax_registrations
                    (entity_id, tax_type, jurisdiction, registration_number,
                     effective_from, effective_to, filing_cadence, notes, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (entity_id, tax_type, jurisdiction, registration_number,
                 effective_from, effective_to, filing_cadence, notes, source),
            )
            return cur.fetchone()[0]

    def supersede(
        self,
        *,
        prior_id: UUID,
        entity_id: UUID,
        tax_type: str,
        jurisdiction: str,
        registration_number: Optional[str] = None,
        effective_from: Optional[date] = None,
        effective_to: Optional[date] = None,
        filing_cadence: Optional[str] = None,
        notes: Optional[str] = None,
        source: str = "user_explicit",
    ) -> UUID:
        """Insert a corrected row that supersedes a prior one. Original preserved."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.tax_registrations
                    (entity_id, tax_type, jurisdiction, registration_number,
                     effective_from, effective_to, filing_cadence, notes,
                     supersedes_id, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (entity_id, tax_type, jurisdiction, registration_number,
                 effective_from, effective_to, filing_cadence, notes,
                 prior_id, source),
            )
            return cur.fetchone()[0]

    def list_live(self, entity_id: UUID) -> list[TaxRegistration]:
        """Return the leaf rows of supersedes chains for this entity."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS}
                FROM goldman.tax_registrations_live
                WHERE entity_id = %s
                ORDER BY created_at
                """,
                (entity_id,),
            )
            return [_row_to_obj(r) for r in cur.fetchall()]
