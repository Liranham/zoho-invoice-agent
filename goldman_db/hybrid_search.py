"""Python wrapper for the goldman.hybrid_search RPC."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID


def _vec_to_str(v) -> str:
    return "[" + ",".join(str(x) for x in v) + "]"


@dataclass(frozen=True)
class HybridSearchResult:
    source_type: str       # 'fact' / 'turn' / 'chunk'
    source_id: UUID
    excerpt: str
    score: float
    entity_id: Optional[UUID]
    metadata: dict


def hybrid_search(
    conn,
    *,
    query_embedding,
    query_text: str,
    entity_id: Optional[UUID] = None,
    top_n: int = 20,
    rrf_k: int = 60,
) -> list:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM goldman.hybrid_search(
                %s::vector(1536), %s, %s, %s, %s
            )
            """,
            (_vec_to_str(query_embedding), query_text,
             entity_id, top_n, rrf_k),
        )
        rows = cur.fetchall()
    return [
        HybridSearchResult(
            source_type=r[0],
            source_id=r[1],
            excerpt=r[2],
            score=float(r[3]),
            entity_id=r[4],
            metadata=r[5] or {},
        )
        for r in rows
    ]
