"""Repository for goldman.clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class Client:
    id: UUID
    entity_id: UUID
    zoho_contact_id: str
    contact_name: str
    company_name: Optional[str]
    primary_email: Optional[str]
    tier: Optional[str]
    primary_contact: Optional[str]
    notes: Optional[str]


_COLS = """
    id, entity_id, zoho_contact_id, contact_name, company_name,
    primary_email, tier, primary_contact, notes
"""


def _row(r) -> Client:
    return Client(
        id=r[0], entity_id=r[1], zoho_contact_id=r[2],
        contact_name=r[3], company_name=r[4], primary_email=r[5],
        tier=r[6], primary_contact=r[7], notes=r[8],
    )


class ClientRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def upsert_by_zoho_id(
        self,
        *,
        entity_id: UUID,
        zoho_contact_id: str,
        contact_name: str,
        company_name: Optional[str] = None,
        primary_email: Optional[str] = None,
    ) -> UUID:
        """Insert or update on (entity_id, zoho_contact_id). Returns the row id."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.clients
                    (entity_id, zoho_contact_id, contact_name,
                     company_name, primary_email, last_synced_at)
                VALUES (%s, %s, %s, %s, %s, now())
                ON CONFLICT (entity_id, zoho_contact_id) DO UPDATE
                    SET contact_name = EXCLUDED.contact_name,
                        company_name = EXCLUDED.company_name,
                        primary_email = EXCLUDED.primary_email,
                        last_synced_at = now()
                RETURNING id
                """,
                (entity_id, zoho_contact_id, contact_name,
                 company_name, primary_email),
            )
            return cur.fetchone()[0]

    def list_by_entity(self, entity_id: UUID) -> list[Client]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.clients "
                f"WHERE entity_id = %s ORDER BY contact_name",
                (entity_id,),
            )
            return [_row(r) for r in cur.fetchall()]

    def set_tier(self, client_id: UUID, tier: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE goldman.clients SET tier = %s WHERE id = %s",
                (tier, client_id),
            )
