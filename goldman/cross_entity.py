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
    """Stub — Task 2 implements."""
    raise NotImplementedError("last_tp_doc — implemented in Task 2")
