# Goldman Phase 6.4 — Cross-Entity Insights in `who` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface two cross-entity facts inline in `goldman who` (CLI + API + plugin): intercompany flow in the last 30 days (both directions per entity) and the most recent TP documentation on file. No schema migration; pure read-side aggregation.

**Architecture:** New pure-Python module `goldman/cross_entity.py` with two SQL-backed query functions. `goldman/who.py` `EntitySummary` gains two fields populated by `build_who_view` from each entity's counterparts. `render_who`, API serialiser, and plugin `jq` template each gain a small rendering block. Tests are MagicMock-based following the existing project pattern.

**Tech Stack:** Python 3.9, existing `psycopg`, `pytest`. No new dependencies. No schema changes.

---

## File Map

**Create:**
- `goldman/cross_entity.py` — two pure functions: `intercompany_flow(conn, ...)` and `last_tp_doc(conn, ...)`.
- `tests/test_goldman_cross_entity.py` — 4 unit tests.

**Modify:**
- `goldman/who.py` — extend `EntitySummary` with `intercompany_flow: dict` and `last_tp_doc: Optional[dict]`; extend `build_who_view` to accept `conn` and call cross_entity; extend `render_who` with two new line blocks.
- `tests/test_goldman_who.py` — update existing fixtures and add a coverage test for the new fields.
- `goldman/api/endpoints.py` — `_serialise_summary` includes the two new fields in the JSON output.
- `tests/test_goldman_api_endpoints.py` — extend `test_handle_who_returns_summary_list` to assert the new fields exist.
- `goldman.plugin/commands/who.md` — extend `jq` rendering to print the new fields.
- `cli.py` `who_cmd`, `goldman/bot/tools.py` `_who`, `goldman/api/endpoints.py` `handle_who` — pass `conn` to `build_who_view`.

---

## Task 1: `goldman/cross_entity.py` — `intercompany_flow` (TDD)

**Files:**
- Create: `goldman/cross_entity.py`
- Create: `tests/test_goldman_cross_entity.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_cross_entity.py`:

```python
"""Tests for cross-entity insight primitives."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from goldman.cross_entity import intercompany_flow, last_tp_doc


def test_intercompany_flow_aggregates_count_total_and_currency():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    # 3 bills totaling 1200.00 USD
    cur.fetchall.return_value = [
        (400.00, "USD"),
        (500.00, "USD"),
        (300.00, "USD"),
    ]

    eid_a = uuid4()
    result = intercompany_flow(
        conn=conn,
        entity_a_id=eid_a,
        entity_b_legal_name="Specific Edge Outsourcing LLC",
        days=30,
    )

    assert result["count"] == 3
    assert result["total"] == 1200.00
    assert result["currency"] == "USD"

    sql = str(cur.execute.call_args)
    assert "goldman.bills" in sql
    assert "vendor_name_at_intake" in sql
    # Bound parameter contains the entity_a id
    params = cur.execute.call_args[0][1]
    assert eid_a in params


def test_intercompany_flow_mixed_currencies_marks_mixed():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [
        (100.00, "USD"),
        (50.00, "HKD"),
    ]

    result = intercompany_flow(
        conn=conn,
        entity_a_id=uuid4(),
        entity_b_legal_name="X",
        days=30,
    )

    assert result["count"] == 2
    assert result["total"] == 150.00
    assert result["currency"] == "mixed"


def test_intercompany_flow_no_rows_returns_zero_result():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    result = intercompany_flow(
        conn=conn,
        entity_a_id=uuid4(),
        entity_b_legal_name="X",
        days=30,
    )

    assert result == {"count": 0, "total": 0.0, "currency": None}
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd ~/Desktop/Obsidian/Projects/zoho-invoice-agent && \
python3 -m pytest tests/test_goldman_cross_entity.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'goldman.cross_entity'`.

- [ ] **Step 3: Implement `intercompany_flow`**

Create `goldman/cross_entity.py`:

```python
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
    whitespace-tolerant substring on the longer name).
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
```

- [ ] **Step 4: Run — should pass**

```bash
python3 -m pytest tests/test_goldman_cross_entity.py -v 2>&1 | tail -8
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add goldman/cross_entity.py tests/test_goldman_cross_entity.py && \
git commit -m "Add intercompany_flow primitive (Phase 6.4 part 1)

Pure function: queries goldman.bills filed by entity_a against vendor
matching entity_b's legal_name in the last N days. Returns count + total
+ currency (or 'mixed' when multiple distinct currencies).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `last_tp_doc` (TDD)

**Files:**
- Modify: `goldman/cross_entity.py`
- Modify: `tests/test_goldman_cross_entity.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_goldman_cross_entity.py`:

```python
def test_last_tp_doc_prefers_knowledge_pack():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    # First query (preferred path) returns a knowledge_pack row
    cur.fetchone.return_value = (
        "transfer_pricing_hk_us_v1.md",
        "knowledge_pack",
        "v1-2026-06",
        datetime(2026, 6, 9, tzinfo=timezone.utc),
    )

    result = last_tp_doc(
        conn=conn,
        entity_a_legal_name="AMZ Expert Global Limited",
        entity_b_legal_name="Specific Edge Outsourcing LLC",
    )

    assert result is not None
    assert result["filename"] == "transfer_pricing_hk_us_v1.md"
    assert result["source"] == "knowledge_pack"
    assert result["pack_version"] == "v1-2026-06"
    assert result["uploaded_at"] == "2026-06-09T00:00:00+00:00"

    sql_first = str(cur.execute.call_args_list[0])
    assert "knowledge_pack" in sql_first
    assert "transfer_pricing_hk_us" in sql_first


def test_last_tp_doc_falls_back_when_no_pack():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    # First (preferred) query returns nothing; second (fallback) returns a row
    cur.fetchone.side_effect = [
        None,
        (
            "2025-cpa-letter.pdf",
            "uploaded",
            None,
            datetime(2025, 11, 15, tzinfo=timezone.utc),
        ),
    ]

    result = last_tp_doc(
        conn=conn,
        entity_a_legal_name="AMZ Expert Global Limited",
        entity_b_legal_name="Specific Edge Outsourcing LLC",
    )

    assert result is not None
    assert result["filename"] == "2025-cpa-letter.pdf"
    assert result["source"] == "uploaded"
    assert result["pack_version"] is None

    # Two queries executed — preferred + fallback
    assert cur.execute.call_count == 2


def test_last_tp_doc_returns_none_when_nothing_found():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [None, None]

    result = last_tp_doc(
        conn=conn,
        entity_a_legal_name="X", entity_b_legal_name="Y",
    )

    assert result is None
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_cross_entity.py::test_last_tp_doc_prefers_knowledge_pack -v 2>&1 | tail -5
```

Expected: `ImportError: cannot import name 'last_tp_doc' from 'goldman.cross_entity'`.

- [ ] **Step 3: Append `last_tp_doc` to `goldman/cross_entity.py`**

Add to `goldman/cross_entity.py`:

```python
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
```

- [ ] **Step 4: Run — all 6 tests pass**

```bash
python3 -m pytest tests/test_goldman_cross_entity.py -v 2>&1 | tail -10
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add goldman/cross_entity.py tests/test_goldman_cross_entity.py && \
git commit -m "Add last_tp_doc primitive (Phase 6.4 part 2)

Two-pass query: prefers source='knowledge_pack' + pack_topic
='transfer_pricing_hk_us'. Falls back to any non-pack document whose
summary or filename mentions both entity legal names. Returns the most
recent by uploaded_at.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Extend `EntitySummary` + `build_who_view` + `render_who` (TDD)

**Files:**
- Modify: `goldman/who.py`
- Modify: `tests/test_goldman_who.py`

- [ ] **Step 1: Read the existing tests**

```bash
cat tests/test_goldman_who.py
```

Note the existing fixtures use MagicMock to build fake entities and repos. The MagicMock-based entity fixtures will continue to work as long as `getattr(ent, 'fiscal_year_end', None)` still resolves — but we'll inject cross_entity behaviour by patching it.

- [ ] **Step 2: Write the failing test** — extend `tests/test_goldman_who.py`

Append to `tests/test_goldman_who.py`:

```python
from unittest.mock import patch


def test_build_who_view_populates_cross_entity_fields_when_counterparts_exist():
    amzg_id = uuid4()
    seo_id = uuid4()
    entities = [
        MagicMock(
            id=amzg_id, slug="amzg",
            legal_name="AMZ Expert Global Limited",
            jurisdiction="HK", parent_entity_id=None,
            base_currency="HKD", fiscal_year_end="03-31",
            registered_address="Suite 100", company_number="HK-12345",
            incorporation_date=date(2024, 1, 1),
        ),
        MagicMock(
            id=seo_id, slug="seo",
            legal_name="Specific Edge Outsourcing LLC",
            jurisdiction="US", parent_entity_id=amzg_id,
            base_currency="USD", fiscal_year_end=None,
            registered_address=None, company_number=None,
            incorporation_date=None,
        ),
    ]
    entities_repo = MagicMock(); entities_repo.list_all.return_value = entities
    tax_repo = MagicMock(); tax_repo.list_live.return_value = []
    bank_repo = MagicMock(); bank_repo.list_by_entity.return_value = []
    clients_repo = MagicMock(); clients_repo.list_by_entity.return_value = []
    vendors_repo = MagicMock(); vendors_repo.list_by_entity.return_value = []
    fake_conn = MagicMock()

    flow_for_a = {"count": 2, "total": 800.0, "currency": "USD"}
    flow_for_b = {"count": 1, "total": 1500.0, "currency": "HKD"}
    tp_doc = {
        "filename": "transfer_pricing_hk_us_v1.md",
        "source": "knowledge_pack",
        "pack_version": "v1-2026-06",
        "uploaded_at": "2026-06-09T00:00:00+00:00",
    }

    with patch("goldman.who.intercompany_flow", side_effect=[flow_for_a, flow_for_b]), \
         patch("goldman.who.last_tp_doc", return_value=tp_doc):
        view = build_who_view(
            entities_repo=entities_repo,
            tax_repo=tax_repo, bank_repo=bank_repo,
            clients_repo=clients_repo, vendors_repo=vendors_repo,
            conn=fake_conn,
        )

    assert len(view) == 2
    # build_who_view augments intercompany_flow with a 'counterpart' key.
    ic_a = view[0].intercompany_flow
    assert ic_a["count"] == 2
    assert ic_a["total"] == 800.0
    assert ic_a["currency"] == "USD"
    assert ic_a["counterpart"] == "Specific Edge Outsourcing LLC"
    assert view[0].last_tp_doc == tp_doc
    ic_b = view[1].intercompany_flow
    assert ic_b["count"] == 1
    assert ic_b["total"] == 1500.0
    assert ic_b["currency"] == "HKD"
    assert ic_b["counterpart"] == "AMZ Expert Global Limited"


def test_render_who_includes_intercompany_and_tp_doc_lines():
    summary = EntitySummary(
        id=uuid4(), slug="amzg",
        legal_name="AMZ Expert Global Limited",
        jurisdiction="HK", parent_entity_id=None,
        base_currency="HKD",
        fiscal_year_end="03-31",
        registered_address="Suite 100",
        company_number="HK-12345",
        incorporation_date=None,
        tax_registrations=[], bank_accounts=[],
        top_clients=[], top_vendors=[],
        intercompany_flow={"count": 3, "total": 1200.0, "currency": "USD",
                           "counterpart": "Specific Edge Outsourcing LLC"},
        last_tp_doc={
            "filename": "transfer_pricing_hk_us_v1.md",
            "source": "knowledge_pack",
            "pack_version": "v1-2026-06",
            "uploaded_at": "2026-06-09T00:00:00+00:00",
        },
    )

    output = render_who([summary])

    assert "Intercompany flow" in output
    assert "Specific Edge Outsourcing LLC" in output
    assert "1200" in output or "1,200" in output
    assert "TP documentation" in output or "TP doc" in output
    assert "transfer_pricing_hk_us_v1.md" in output


def test_render_who_handles_no_cross_entity_data():
    summary = EntitySummary(
        id=uuid4(), slug="amzg",
        legal_name="AMZ Expert Global Limited",
        jurisdiction="HK", parent_entity_id=None,
        base_currency="HKD",
        fiscal_year_end="03-31",
        registered_address="Suite 100",
        company_number="HK-12345",
        incorporation_date=None,
        tax_registrations=[], bank_accounts=[],
        top_clients=[], top_vendors=[],
        intercompany_flow={"count": 0, "total": 0.0, "currency": None,
                           "counterpart": None},
        last_tp_doc=None,
    )

    output = render_who([summary])

    assert "Intercompany flow" in output
    assert "TP documentation" in output or "TP doc" in output
    # When there's no flow we should still see a "(none)" or equivalent marker
    assert "(none)" in output or "no intercompany" in output.lower()
```

Also update the **existing** two tests in this file to add the new fields to the EntitySummary fixtures and to pass `conn` to build_who_view. Specifically:

- `test_build_who_view_includes_each_entity` currently calls `build_who_view(...)` without `conn`. Add `conn=MagicMock()`. Also wrap the call in `with patch("goldman.who.intercompany_flow", return_value={...}), patch("goldman.who.last_tp_doc", return_value=None):` so the test runs without real DB.
- `test_render_who_includes_legal_name_and_jurisdiction` constructs an `EntitySummary(...)`. Add `intercompany_flow={"count": 0, "total": 0.0, "currency": None, "counterpart": None}, last_tp_doc=None` to the kwargs.

- [ ] **Step 3: Run — confirm failures**

```bash
python3 -m pytest tests/test_goldman_who.py -v 2>&1 | tail -10
```

Expected: most fail due to missing kwargs or fields.

- [ ] **Step 4: Update `goldman/who.py`**

Replace the entire contents of `goldman/who.py` with:

```python
"""Composable 'who' view of the Goldman company tree.

Build-and-render split: build_who_view returns structured data that
Telegram bot + Claude Code plugin can both consume; render_who is the
plain-text rendering used by CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from uuid import UUID

from goldman.cross_entity import intercompany_flow, last_tp_doc


@dataclass
class EntitySummary:
    id: UUID
    slug: str
    legal_name: str
    jurisdiction: str
    parent_entity_id: Optional[UUID]
    base_currency: str
    fiscal_year_end: Optional[str]
    registered_address: Optional[str]
    company_number: Optional[str]
    incorporation_date: Optional[date]
    tax_registrations: list = field(default_factory=list)
    bank_accounts: list = field(default_factory=list)
    top_clients: list = field(default_factory=list)
    top_vendors: list = field(default_factory=list)
    # Phase 6.4 cross-entity fields
    intercompany_flow: dict = field(default_factory=lambda: {
        "count": 0, "total": 0.0, "currency": None, "counterpart": None,
    })
    last_tp_doc: Optional[dict] = None


def build_who_view(
    *,
    entities_repo,
    tax_repo,
    bank_repo,
    clients_repo,
    vendors_repo,
    conn=None,
    top_n: int = 5,
) -> list:
    """Build a list of EntitySummary objects, parent-first ordering.

    `conn` is required to populate cross-entity fields (intercompany_flow,
    last_tp_doc). When None, those fields stay at their defaults.
    """
    all_entities = entities_repo.list_all()

    result = []
    for ent in all_entities:
        ic_flow = {"count": 0, "total": 0.0, "currency": None, "counterpart": None}
        tp_doc = None
        if conn is not None:
            # Aggregate intercompany flow across all other entities. v1 has
            # only two entities so the loop is a no-op for 1-entity setups
            # and a single counterpart for 2-entity setups.
            counterparts = [e for e in all_entities if e.id != ent.id]
            running = {"count": 0, "total": 0.0, "currencies": set(),
                       "counterpart_label": None}
            for cp in counterparts:
                flow = intercompany_flow(
                    conn=conn,
                    entity_a_id=ent.id,
                    entity_b_legal_name=cp.legal_name,
                )
                if flow["count"] > 0:
                    running["count"] += flow["count"]
                    running["total"] += flow["total"]
                    if flow["currency"] is not None:
                        running["currencies"].add(flow["currency"])
                    # For v1 there's a single counterpart so this label is exact.
                    running["counterpart_label"] = cp.legal_name
            if running["count"] > 0:
                if len(running["currencies"]) == 1:
                    cur = running["currencies"].pop()
                else:
                    cur = "mixed"
                ic_flow = {
                    "count": running["count"],
                    "total": running["total"],
                    "currency": cur,
                    "counterpart": running["counterpart_label"],
                }
            # TP doc: pass both this entity and any counterpart's legal name.
            if counterparts:
                tp_doc = last_tp_doc(
                    conn=conn,
                    entity_a_legal_name=ent.legal_name,
                    entity_b_legal_name=counterparts[0].legal_name,
                )

        s = EntitySummary(
            id=ent.id, slug=ent.slug,
            legal_name=ent.legal_name,
            jurisdiction=ent.jurisdiction,
            parent_entity_id=ent.parent_entity_id,
            base_currency=ent.base_currency,
            fiscal_year_end=getattr(ent, "fiscal_year_end", None),
            registered_address=getattr(ent, "registered_address", None),
            company_number=getattr(ent, "company_number", None),
            incorporation_date=getattr(ent, "incorporation_date", None),
            tax_registrations=tax_repo.list_live(ent.id),
            bank_accounts=bank_repo.list_by_entity(ent.id),
            top_clients=clients_repo.list_by_entity(ent.id)[:top_n],
            top_vendors=vendors_repo.list_by_entity(ent.id)[:top_n],
            intercompany_flow=ic_flow,
            last_tp_doc=tp_doc,
        )
        result.append(s)
    return result


def render_who(summaries) -> str:
    """Render summaries as plain text, parent-first then children."""
    lines = []
    for s in summaries:
        prefix = "  -> " if s.parent_entity_id else ""
        lines.append(f"\n{prefix}{s.legal_name} ({s.slug})")
        lines.append(f"   Jurisdiction:     {s.jurisdiction}")
        lines.append(f"   Base currency:    {s.base_currency}")
        lines.append(f"   Fiscal year end:  {s.fiscal_year_end or '-- missing --'}")
        lines.append(f"   Registered addr:  {s.registered_address or '-- missing --'}")
        lines.append(f"   Company number:   {s.company_number or '-- missing --'}")

        lines.append("   Tax registrations:")
        if s.tax_registrations:
            for tr in s.tax_registrations:
                regn = tr.registration_number or "(no number)"
                cad = tr.filing_cadence or "(no cadence)"
                lines.append(f"     - {tr.tax_type} / {tr.jurisdiction} - {regn} [{cad}]")
        else:
            lines.append("     (none)")

        lines.append("   Bank accounts:")
        if s.bank_accounts:
            for ba in s.bank_accounts:
                lines.append(f"     - {ba.provider} - {ba.account_label} ({ba.currency})")
        else:
            lines.append("     (none)")

        lines.append(f"   Top clients ({len(s.top_clients)}):")
        for c in s.top_clients:
            tier = f" [tier {c.tier}]" if c.tier else ""
            lines.append(f"     - {c.contact_name}{tier}")

        lines.append(f"   Top vendors ({len(s.top_vendors)}):")
        for v in s.top_vendors:
            cat = f" - {v.category}" if v.category else ""
            lines.append(f"     - {v.vendor_name}{cat}")

        # Phase 6.4: intercompany flow (last 30 days)
        flow = s.intercompany_flow or {}
        lines.append("   Intercompany flow (30d):")
        if flow.get("count", 0) > 0:
            cur = flow.get("currency") or ""
            cp = flow.get("counterpart") or "(unknown)"
            total = flow.get("total", 0.0)
            lines.append(
                f"     -> {cp}: {total:,.2f} {cur} across "
                f"{flow['count']} bill{'s' if flow['count'] != 1 else ''}"
            )
        else:
            lines.append("     (none)")

        # Phase 6.4: last TP doc on file
        tp = s.last_tp_doc
        lines.append("   TP documentation:")
        if tp:
            label = (
                f"{tp['source']}: {tp.get('pack_version') or tp['filename']}"
                if tp["source"] == "knowledge_pack"
                else tp["filename"]
            )
            uploaded = tp.get("uploaded_at") or ""
            short_date = uploaded[:10] if uploaded else "(unknown date)"
            lines.append(f"     {label} (uploaded {short_date})")
        else:
            lines.append("     (no TP documentation on file)")

    return "\n".join(lines).lstrip("\n")
```

- [ ] **Step 5: Run — all tests pass**

```bash
python3 -m pytest tests/test_goldman_who.py -v 2>&1 | tail -12
```

Expected: 5 tests pass (2 original + 3 new).

- [ ] **Step 6: Commit**

```bash
git add goldman/who.py tests/test_goldman_who.py && \
git commit -m "Phase 6.4: extend EntitySummary + build_who_view + render_who

EntitySummary gains intercompany_flow (dict) + last_tp_doc (Optional[dict]).
build_who_view aggregates flow across all counterparts per entity and
calls last_tp_doc once per entity (passing one counterpart's legal name).
render_who adds two new sections per entity. build_who_view now accepts
an optional 'conn' kwarg; without conn the cross-entity fields stay at
defaults.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Update all `build_who_view` callers to pass `conn`

**Files:**
- Modify: `cli.py` (who_cmd)
- Modify: `goldman/api/endpoints.py` (handle_who)
- Modify: `goldman/bot/tools.py` (_who)

- [ ] **Step 1: Update `cli.py`**

In `cli.py`, find `def who_cmd():` and update the `build_who_view(...)` call to pass `conn=conn`. The change is one kwarg addition:

```python
with app_conn() as conn:
    summaries = build_who_view(
        entities_repo=EntityRepository(conn),
        tax_repo=TaxRegistrationRepository(conn),
        bank_repo=BankAccountRepository(conn),
        clients_repo=ClientRepository(conn),
        vendors_repo=VendorRepository(conn),
        conn=conn,                      # <-- new
    )
```

- [ ] **Step 2: Update `goldman/api/endpoints.py` handle_who**

Find `def handle_who(*, query, body):` in `goldman/api/endpoints.py`. Update the `build_who_view(...)` call inside its `with app_conn() as conn:` block to pass `conn=conn`:

```python
with app_conn() as conn:
    summaries = build_who_view(
        entities_repo=EntityRepository(conn),
        tax_repo=TaxRegistrationRepository(conn),
        bank_repo=BankAccountRepository(conn),
        clients_repo=ClientRepository(conn),
        vendors_repo=VendorRepository(conn),
        conn=conn,                      # <-- new
    )
return 200, {"entities": [_serialise_summary(s) for s in summaries]}
```

- [ ] **Step 3: Update `goldman/bot/tools.py` `_who`**

Find `def _who(ctx):` in `goldman/bot/tools.py`. Update the `build_who_view(...)` call to pass `conn=ctx.conn`:

```python
summaries = build_who_view(
    entities_repo=EntityRepository(ctx.conn),
    tax_repo=TaxRegistrationRepository(ctx.conn),
    bank_repo=BankAccountRepository(ctx.conn),
    clients_repo=ClientRepository(ctx.conn),
    vendors_repo=VendorRepository(ctx.conn),
    conn=ctx.conn,                      # <-- new
)
```

- [ ] **Step 4: Sanity import-check + commit**

```bash
python3 -c "import cli, goldman.api.endpoints, goldman.bot.tools; print('OK')"
```

Expected: `OK`.

```bash
git add cli.py goldman/api/endpoints.py goldman/bot/tools.py && \
git commit -m "Phase 6.4: pass conn to build_who_view from all callers

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Update `goldman/api/endpoints.py` serialiser + test

**Files:**
- Modify: `goldman/api/endpoints.py` (_serialise_summary)
- Modify: `tests/test_goldman_api_endpoints.py`

- [ ] **Step 1: Update `_serialise_summary`**

In `goldman/api/endpoints.py`, find `def _serialise_summary(s):` and add the two new fields at the end of the returned dict:

```python
def _serialise_summary(s) -> dict:
    return {
        "slug": s.slug,
        "legal_name": s.legal_name,
        "jurisdiction": s.jurisdiction,
        "parent_entity_id": str(s.parent_entity_id) if getattr(s, "parent_entity_id", None) else None,
        "base_currency": s.base_currency,
        "fiscal_year_end": s.fiscal_year_end,
        "registered_address": s.registered_address,
        "company_number": s.company_number,
        "tax_registrations": [
            {"tax_type": tr.tax_type, "jurisdiction": tr.jurisdiction,
             "registration_number": tr.registration_number,
             "filing_cadence": tr.filing_cadence}
            for tr in s.tax_registrations
        ],
        "bank_accounts": [
            {"provider": b.provider, "account_label": b.account_label,
             "currency": b.currency}
            for b in s.bank_accounts
        ],
        "top_clients": [
            {"name": c.contact_name, "tier": c.tier}
            for c in s.top_clients
        ],
        "top_vendors": [
            {"name": v.vendor_name, "category": v.category}
            for v in s.top_vendors
        ],
        # Phase 6.4 cross-entity fields
        "intercompany_flow": getattr(s, "intercompany_flow", None) or {
            "count": 0, "total": 0.0, "currency": None, "counterpart": None,
        },
        "last_tp_doc": getattr(s, "last_tp_doc", None),
    }
```

- [ ] **Step 2: Update the existing `test_handle_who_returns_summary_list` test**

In `tests/test_goldman_api_endpoints.py`, find the existing `test_handle_who_returns_summary_list`. Update the MagicMock fixture to include the new fields:

```python
def test_handle_who_returns_summary_list():
    with patch("goldman.api.endpoints.app_conn") as mock_conn, \
         patch("goldman.api.endpoints.build_who_view") as mock_build:
        mock_conn.return_value.__enter__.return_value = MagicMock()
        mock_build.return_value = [
            MagicMock(slug="amzg", legal_name="AMZ Expert Global Limited",
                       jurisdiction="HK", parent_entity_id=None,
                       base_currency="HKD", fiscal_year_end=None,
                       registered_address=None, company_number=None,
                       tax_registrations=[], bank_accounts=[],
                       top_clients=[], top_vendors=[],
                       intercompany_flow={"count": 2, "total": 800.0,
                                          "currency": "USD",
                                          "counterpart": "Specific Edge Outsourcing LLC"},
                       last_tp_doc={
                           "filename": "transfer_pricing_hk_us_v1.md",
                           "source": "knowledge_pack",
                           "pack_version": "v1-2026-06",
                           "uploaded_at": "2026-06-09T00:00:00+00:00",
                       }),
        ]

        code, body = handle_who(query={}, body={})

        assert code == 200
        assert "entities" in body
        assert body["entities"][0]["slug"] == "amzg"
        # Phase 6.4 fields surfaced in serialised JSON:
        ic = body["entities"][0]["intercompany_flow"]
        assert ic["count"] == 2
        assert ic["counterpart"] == "Specific Edge Outsourcing LLC"
        tp = body["entities"][0]["last_tp_doc"]
        assert tp["filename"] == "transfer_pricing_hk_us_v1.md"
```

- [ ] **Step 3: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_api_endpoints.py -v 2>&1 | tail -10
```

Expected: all 6 tests pass (with the updated `test_handle_who_returns_summary_list`).

```bash
git add goldman/api/endpoints.py tests/test_goldman_api_endpoints.py && \
git commit -m "Phase 6.4: include intercompany_flow + last_tp_doc in /v1/who JSON

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Update plugin `/goldman:who` jq rendering

**Files:**
- Modify: `goldman.plugin/commands/who.md`

The current rendering uses a single jq pipeline. Add two new lines at the bottom of the jq filter so the plugin output mirrors the CLI shape.

- [ ] **Step 1: Replace the jq pipeline**

Replace the bash block in `goldman.plugin/commands/who.md` with:

```bash
URL="${GOLDMAN_API_URL:-https://goldman.onrender.com}"
KEY="${GOLDMAN_API_KEY:-}"
if [ -z "$KEY" ]; then
  echo "GOLDMAN_API_KEY not set"
  exit 1
fi
curl -s -H "Authorization: Bearer $KEY" "$URL/v1/who" | \
  jq -r '
    .entities[] |
    "\n\(.legal_name) (\(.slug))" +
    "\n  Jurisdiction:      \(.jurisdiction)" +
    "\n  Tax registrations: \(.tax_registrations | length)" +
    "\n  Bank accounts:     \(.bank_accounts | length)" +
    "\n  Top clients:       \(.top_clients | length)" +
    "\n  Top vendors:       \(.top_vendors | length)" +
    "\n  Intercompany flow (30d): \(
        if (.intercompany_flow.count // 0) > 0 then
          "-> \(.intercompany_flow.counterpart): \(.intercompany_flow.total) \(.intercompany_flow.currency) across \(.intercompany_flow.count) bill(s)"
        else "(none)" end
      )" +
    "\n  TP documentation:   \(
        if .last_tp_doc then
          "\(.last_tp_doc.filename) (\(.last_tp_doc.uploaded_at[0:10]))"
        else "(none on file)" end
      )"
  '
```

- [ ] **Step 2: Commit**

```bash
git add goldman.plugin/commands/who.md && \
git commit -m "Phase 6.4: extend /goldman:who plugin to display cross-entity fields

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Full regression + memory update

**Files:** (no code changes; checkpoint)

- [ ] **Step 1: Full test sweep**

```bash
cd ~/Desktop/Obsidian/Projects/zoho-invoice-agent && \
python3 -m pytest 2>&1 | tail -3
```

Expected: every test passes. Prior 170 + Phase 6.4's new tests (≈6) = ~176 total.

- [ ] **Step 2: Live `who` against the real DB (no Telegram needed)**

```bash
python3 cli.py who 2>&1 | head -40
```

Expected: each entity now shows new sections:
```
   Intercompany flow (30d):
     (none)
   TP documentation:
     (no TP documentation on file)
```

(`(none)` until bills are filed; `(no TP documentation on file)` until packs are ingested with `pack add` and `db embed-pending`.)

- [ ] **Step 3: Update memory**

Append to `~/.claude/projects/-Users-hamburg/memory/project_goldman.md`:

```markdown
- **Phase 6.4 (cross-entity insights in who) code = COMPLETE 2026-06-09.** New module `goldman/cross_entity.py` with two pure functions: `intercompany_flow(conn, entity_a_id, entity_b_legal_name, days=30)` aggregates bills filed by A whose vendor name matches B (count + total + currency 'USD'|'mixed'|None) — case-insensitive whitespace-tolerant SQL substring match. `last_tp_doc(conn, a_legal_name, b_legal_name)` returns most recent goldman.documents row preferring source='knowledge_pack' + pack_topic='transfer_pricing_hk_us', falling back to any document mentioning both entities in summary or filename. `goldman.who.EntitySummary` gains `intercompany_flow` (dict) + `last_tp_doc` (Optional[dict]); `build_who_view` accepts optional `conn` kwarg and populates them. `render_who` adds 2 new sections per entity. `/v1/who` API JSON includes the fields. Plugin `/goldman:who` extends jq pipeline to render them. No schema migration. 6 new tests, ~176 total. Each entity shows '(none)' until bills are filed AND tax packs are ingested via 'pack add'.
```

---

## Spec coverage cross-check

| Spec section | Covered by task(s) |
|---|---|
| §2 — `goldman/cross_entity.py` two pure functions | Tasks 1, 2 |
| §2 — `EntitySummary` two new fields | Task 3 |
| §2 — `build_who_view` populates them | Task 3 + Task 4 (callers pass conn) |
| §2 — `render_who` two new line blocks | Task 3 |
| §2 — API serialiser includes them | Task 5 |
| §2 — plugin `jq` renders them | Task 6 |
| §3 — Intercompany flow definition (case-insensitive, last `days`) | Task 1 (SQL LOWER+REGEXP_REPLACE match) |
| §3 — TP doc preferred vs fallback | Task 2 (two-pass query) |
| §5 — Failure modes (no bills, no docs, mixed currency) | Tasks 1, 2 (returns shapes), 3 (render handles `(none)`) |

All spec requirements covered.

---

## What's intentionally NOT in this plan

- Flag table (`goldman.cross_entity_flags`) — explicitly v2 per spec §6.
- Anomaly detection on amount deviation — declined this turn.
- Proactive Telegram alerts when intercompany bill lacks TP doc — v2.
- New CLI commands (e.g. `intercompany list`) — only `who` enhancement in v1.
- Adding `goldman.vendors.counterparty_entity_id` — deferred per spec §4.
