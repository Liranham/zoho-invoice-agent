"""Decision recall primitive (Phase 6.5).

Pure function backed by SQL against goldman.facts_live. Returns a
chronological list of decision-kind facts matching the topic.
"""

from __future__ import annotations

from typing import Optional


def decision_timeline(
    *,
    conn,
    topic: str,
    entity_slug: Optional[str] = None,
    limit: int = 20,
) -> list:
    """Return decision facts whose text matches `topic` (case-insensitive
    substring), most recent first.

    When entity_slug is provided, restricts to that entity OR cross-entity
    facts (entity_id IS NULL).
    """
    if not topic or not topic.strip():
        raise ValueError("topic must be a non-empty string")

    with conn.cursor() as cur:
        if entity_slug is None:
            cur.execute(
                """
                SELECT f.id, f.fact, e.slug AS entity_slug, f.entity_id,
                       f.created_at, f.supersedes_id
                FROM goldman.facts_live f
                LEFT JOIN goldman.entities e ON e.id = f.entity_id
                WHERE f.kind = 'decision'
                  AND f.fact ILIKE '%%' || %s || '%%'
                ORDER BY f.created_at DESC
                LIMIT %s
                """,
                (topic, limit),
            )
        else:
            cur.execute(
                """
                SELECT f.id, f.fact, e.slug AS entity_slug, f.entity_id,
                       f.created_at, f.supersedes_id
                FROM goldman.facts_live f
                LEFT JOIN goldman.entities e ON e.id = f.entity_id
                WHERE f.kind = 'decision'
                  AND f.fact ILIKE '%%' || %s || '%%'
                  AND (e.slug = %s OR f.entity_id IS NULL)
                ORDER BY f.created_at DESC
                LIMIT %s
                """,
                (topic, entity_slug, limit),
            )
        rows = cur.fetchall()

    return [
        {
            "id": r[0],
            "fact": r[1],
            "entity_slug": r[2],
            "created_at": r[4].isoformat() if r[4] else None,
            "supersedes_id": r[5],
        }
        for r in rows
    ]
