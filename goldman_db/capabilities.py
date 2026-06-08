"""Repository for goldman.capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class Capability:
    id: UUID
    name: str
    description: str
    kind: str
    payload: dict
    is_active: bool


_COLS = "id, name, description, kind, payload, is_active"


def _row(r) -> Capability:
    return Capability(
        id=r[0], name=r[1], description=r[2],
        kind=r[3], payload=r[4] or {}, is_active=r[5],
    )


class CapabilityRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def list_active(self) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.capabilities "
                f"WHERE is_active = true ORDER BY kind, name"
            )
            return [_row(r) for r in cur.fetchall()]

    def list_by_kind(self, kind: str) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.capabilities "
                f"WHERE kind = %s AND is_active = true ORDER BY name",
                (kind,),
            )
            return [_row(r) for r in cur.fetchall()]

    def get_by_name(self, name: str) -> Optional[Capability]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.capabilities WHERE name = %s",
                (name,),
            )
            row = cur.fetchone()
            return _row(row) if row else None
