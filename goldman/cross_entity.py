"""Cross-entity insight primitives (Phase 6.4).

Two pure functions backed by SQL against the existing schema. No new
tables. Consumed by goldman.who.build_who_view and goldman.api.endpoints.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID


def intercompany_flow(
    *,
    conn,
    entity_a_id: UUID,
    entity_b_legal_name: str,
    days: int = 30,
) -> dict:
    """Return {'count', 'total', 'currency'} for bills entity_a filed against
    entity_b in the last `days` days.

    A bill is intercompany when entity_id = entity_a_id AND
    vendor_name_at_intake matches entity_b's legal name (case-insensitive,
    whitespace-tolerant substring).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT amount, currency FROM goldman.bills
            WHERE entity_id = %s
              AND LOWER(REGEXP_REPLACE(vendor_name_at_intake, '\\s+', ' ', 'g'))
                  LIKE '%%' || LOWER(REGEXP_REPLACE(%s, '\\s+', ' ', 'g')) || '%%'
              AND created_at >= NOW() - (%s || ' days')::interval
            """,
            (entity_a_id, entity_b_legal_name, str(days)),
        )
        rows = cur.fetchall()

    if not rows:
        return {"count": 0, "total": 0.0, "currency": None}

    total = sum(float(r[0]) for r in rows)
    currencies = {r[1] for r in rows}
    currency = currencies.pop() if len(currencies) == 1 else "mixed"
    return {"count": len(rows), "total": total, "currency": currency}


def last_tp_doc(
    *,
    conn,
    entity_a_legal_name: str,
    entity_b_legal_name: str,
) -> Optional[dict]:
    """Return the most recent goldman.documents row that is either:
      (a) source='knowledge_pack' AND pack_topic='transfer_pricing_hk_us', OR
      (b) source != 'knowledge_pack' AND (summary OR filename) mentions both
          entity legal names (case-insensitive).
    Picks most recent by uploaded_at DESC. Returns None if neither pass finds a row.
    """
    with conn.cursor() as cur:
        # Preferred: explicit transfer-pricing knowledge_pack
        cur.execute(
            """
            SELECT filename, source, pack_version, uploaded_at
            FROM goldman.documents
            WHERE source = 'knowledge_pack'
              AND pack_topic = 'transfer_pricing_hk_us'
            ORDER BY uploaded_at DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if row is None:
            # Fallback: any document mentioning both entity legal names
            cur.execute(
                """
                SELECT filename, source, pack_version, uploaded_at
                FROM goldman.documents
                WHERE source != 'knowledge_pack'
                  AND (
                       (summary ILIKE '%%' || %s || '%%' AND summary ILIKE '%%' || %s || '%%')
                       OR
                       (filename ILIKE '%%' || %s || '%%' AND filename ILIKE '%%' || %s || '%%')
                  )
                ORDER BY uploaded_at DESC
                LIMIT 1
                """,
                (entity_a_legal_name, entity_b_legal_name,
                 entity_a_legal_name, entity_b_legal_name),
            )
            row = cur.fetchone()

    if row is None:
        return None
    filename, source, pack_version, uploaded_at = row
    return {
        "filename": filename,
        "source": source,
        "pack_version": pack_version,
        "uploaded_at": uploaded_at.isoformat() if uploaded_at else None,
    }
