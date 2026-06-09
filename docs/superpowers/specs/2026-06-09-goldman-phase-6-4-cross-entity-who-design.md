# Goldman Phase 6.4 — Cross-Entity Insights in `who` (read-side only)

**Date:** 2026-06-09
**Author:** Liran Hamburg + Claude
**Status:** Design, pre-implementation
**Scope:** Smallest-cost cross-entity visibility. No flag table, no proactive detection, no schema change. Future v2+ can add detection on top of the same query primitives.

---

## 1. Goal

Add two pieces of cross-entity context to `goldman who` (CLI, API, plugin) without introducing any new infrastructure:

1. **Intercompany flow this period** (last 30 days), both directions: how much money flowed AMZG → SEO and SEO → AMZG, plus the number of bills in each direction.
2. **Last TP documentation on file** — the most recent goldman.documents row that's either a `knowledge_pack` with `pack_topic = 'transfer_pricing_hk_us'` or any other document whose summary/filename mentions both entity legal names.

When Liran runs `goldman who`, asks the Telegram bot "who", or hits `/v1/who` from the Claude Code plugin, he sees these two facts inline per entity. No proactive alerts; no flag table; no anomaly detection in v1.

## 2. What changes (minimum footprint)

**No schema migrations.** No new tables, no new columns, no new indexes.

**One new pure-Python module** — `goldman/cross_entity.py`:

```python
def intercompany_flow(
    *, conn, entity_a_id: UUID, entity_b_legal_name: str, days: int = 30,
) -> dict:
    """Return {'count': N, 'total': X, 'currency': 'mixed' or specific}
    for bills where entity_a is the billing entity AND vendor_name_at_intake
    matches entity_b's legal name (case-insensitive, fuzzy)."""
    ...


def last_tp_doc(
    *, conn, entity_a_legal_name: str, entity_b_legal_name: str,
) -> Optional[dict]:
    """Return the most recent goldman.documents row that is either:
      (a) source='knowledge_pack' AND pack_topic = 'transfer_pricing_hk_us'
      (b) summary or filename mentions both entity legal names
    Returns {'filename', 'source', 'pack_version', 'uploaded_at'} or None."""
    ...
```

**`goldman/who.py`** — extend `EntitySummary` with two new optional fields and have `build_who_view` populate them when the entity has at least one counterpart in `entities`. `render_who` adds two lines per entity.

**`goldman/api/endpoints.py`** — `_serialise_summary` includes the two new fields in the JSON.

**`goldman.plugin/commands/who.md`** — extend the `jq` rendering to display them.

**Tests:** four new pure-function tests + one integration test of `build_who_view` producing the new fields when entity counterparts exist.

That's the entire surface area.

## 3. Definitions

- **Intercompany flow:** for entity A (e.g. amzg), the sum of `goldman.bills.amount` for bills where `entity_id = A.id` AND `vendor_name_at_intake` matches another entity's `legal_name` (case-insensitive, whitespace-tolerant). Currency reported as 'mixed' when amounts span multiple currencies, otherwise the actual currency.
- **TP documentation:** prefers explicit `knowledge_pack` with `pack_topic = 'transfer_pricing_hk_us'`. Falls back to any document whose `summary` or `filename` contains BOTH entity legal names (case-insensitive substring).
- **Period:** last 30 days from `now()`. Configurable via a default constant in `goldman/cross_entity.py`.
- **Direction:** A → B means a bill filed against A whose vendor is B (A is paying B).

## 4. Why no schema change

Adding `goldman.vendors.counterparty_entity_id` would be cleaner long-term (fast lookups, avoids name-matching fragility). But:

1. It requires a backfill (the sync_zoho_contacts job hasn't been re-run since live data exists).
2. v1 doesn't have proactive flagging — the only consumer of intercompany detection is `who`, which runs on-demand, so a few extra string-matching operations are inconsequential.
3. v2 (if we add the flags table) can add the FK at that point.

YAGNI for v1.

## 5. Failure modes + handling

| Situation | Behaviour |
|---|---|
| No `goldman.bills` rows at all (yet) | `intercompany_flow` returns `{'count': 0, 'total': 0, 'currency': None}`. `render_who` prints "(no intercompany flow)". |
| Only one entity exists | `intercompany_flow` returns the empty result (no counterpart to flow against). |
| TP doc query finds nothing | `last_tp_doc` returns `None`. `render_who` prints "(no TP documentation on file)". |
| Multiple TP docs exist | Pick most recent by `uploaded_at`. Don't list all. |
| Vendor name matches entity loosely (e.g. "AMZ Expert Global Ltd" vs "AMZ Expert Global Limited") | Case-insensitive substring match on the longer of the two normalised names — both inclusive directions. Errors on the side of including. |
| Multiple currencies in the same direction | `currency` field is the string `"mixed"`; `total` is the sum in raw numeric (caller knows it's mixed). |

## 6. Out of scope

- Flag table (`goldman.cross_entity_flags`) — v2 if needed.
- Proactive Telegram alerts when an intercompany bill is filed without supporting docs — v2.
- Anomaly detection (deviation vs trailing average) — explicitly declined this turn.
- Year-over-year comparison — needs historical data Goldman doesn't have yet.
- Cross-entity invoice flow (the inverse direction) — bills only for v1; invoices come later.

## 7. Implementation tasks

| # | Task | Effort |
|---|---|---|
| 1 | `goldman/cross_entity.py` module — TDD `intercompany_flow` + `last_tp_doc` | 45 min |
| 2 | `goldman/who.py` — extend `EntitySummary` + `build_who_view` + `render_who` | 30 min |
| 3 | `goldman/api/endpoints.py` — include in serialised JSON | 10 min |
| 4 | `goldman.plugin/commands/who.md` — extend `jq` rendering | 10 min |
| 5 | Full regression sweep | 5 min |

Total: ~1.5–2 hours of code work.

## 8. Open risks

| Risk | Mitigation |
|---|---|
| Name matching is fragile (e.g. "AMZG Ltd" vs "AMZ Expert Global Limited") | v1 ships with normalised substring match; if Liran reports false positives or misses, we add the FK column in v2. |
| Bills haven't been filed yet, so the section reads "(no intercompany flow)" forever | Cosmetic, expected. As soon as Liran starts using `bill file`, the section comes alive. |
| Multi-currency bills inflate "total" misleadingly | We surface `currency: 'mixed'` to make this explicit. Caller (the renderer) shows the marker. |

---

**Next step:** invoke `superpowers:writing-plans` to convert this spec into a step-by-step implementation plan.
