"""Read-only repository over goldman.entities.

Writes are limited to migrations + the Phase 1 onboarding flow; this module
exposes lookup paths only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import psycopg


_SELECT_COLS = """
    id, slug, legal_name, jurisdiction, parent_entity_id,
    base_currency, zoho_organization_id, zoho_credential_key
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
