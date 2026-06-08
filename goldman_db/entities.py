"""Read-only repository over goldman.entities.

Writes are limited to migrations + the Phase 1 onboarding flow; this module
exposes lookup paths + an update_metadata writer used by onboarding.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional
from uuid import UUID

import psycopg


_SELECT_COLS = """
    id, slug, legal_name, jurisdiction, parent_entity_id,
    base_currency, zoho_organization_id, zoho_credential_key,
    fiscal_year_end, registered_address, company_number, incorporation_date
"""


@dataclass(frozen=True)
class Entity:
    id: UUID
    slug: str
    legal_name: str
    jurisdiction: str
    parent_entity_id: Optional[UUID]
    base_currency: str
    zoho_organization_id: Optional[str]
    zoho_credential_key: Optional[str]
    fiscal_year_end: Optional[str]
    registered_address: Optional[str]
    company_number: Optional[str]
    incorporation_date: Optional[date]


def _row_to_entity(row) -> Entity:
    return Entity(
        id=row[0],
        slug=row[1],
        legal_name=row[2],
        jurisdiction=row[3],
        parent_entity_id=row[4],
        base_currency=row[5],
        zoho_organization_id=row[6],
        zoho_credential_key=row[7],
        fiscal_year_end=row[8],
        registered_address=row[9],
        company_number=row[10],
        incorporation_date=row[11],
    )


class EntityRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def list_all(self) -> list[Entity]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_SELECT_COLS} FROM goldman.entities ORDER BY created_at"
            )
            return [_row_to_entity(row) for row in cur.fetchall()]

    def get_by_slug(self, slug: str) -> Optional[Entity]:
        normalised = slug.lower()
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_SELECT_COLS} FROM goldman.entities WHERE slug = %s",
                (normalised,),
            )
            row = cur.fetchone()
            return _row_to_entity(row) if row else None

    def get_by_id(self, entity_id: UUID) -> Optional[Entity]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_SELECT_COLS} FROM goldman.entities WHERE id = %s",
                (entity_id,),
            )
            row = cur.fetchone()
            return _row_to_entity(row) if row else None

    def update_metadata(self, slug: str, **fields) -> None:
        """Update entity metadata fields. Skips fields whose value is None.

        Allowed fields: fiscal_year_end, registered_address, company_number,
        incorporation_date, zoho_organization_id. Other fields raise ValueError.
        """
        allowed = {
            "fiscal_year_end", "registered_address", "company_number",
            "incorporation_date", "zoho_organization_id",
        }
        clean = {k: v for k, v in fields.items() if v is not None}
        invalid = set(clean.keys()) - allowed
        if invalid:
            raise ValueError(f"Cannot update fields: {invalid}")
        if not clean:
            return
        set_clauses = ", ".join(f"{k} = %s" for k in clean.keys())
        params = list(clean.values()) + [slug.lower()]
        with self.conn.cursor() as cur:
            cur.execute(
                f"UPDATE goldman.entities SET {set_clauses} WHERE slug = %s",
                tuple(params),
            )
