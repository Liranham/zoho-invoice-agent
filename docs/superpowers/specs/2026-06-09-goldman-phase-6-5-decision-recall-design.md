# Goldman Phase 6.5 — Decision Recall

**Date:** 2026-06-09
**Author:** Liran Hamburg + Claude
**Status:** Design, pre-implementation
**Scope:** First-class "what did we decide about X" query type. Returns a chronological timeline of decision-kind facts matching the topic. Read-only addition built on the existing `goldman.facts_live` view.

---

## 1. Goal

When Liran asks Goldman "what did we decide about UK VAT" (or any similar phrasing), he gets a chronological timeline of decisions Goldman knows about, not a relevance-ranked similarity search. The timeline surfaces the same decisions in the same order regardless of phrasing, so Liran can quickly reconstruct prior reasoning.

## 2. What gets built

**New pure-function module** `goldman/decisions.py`:

```python
def decision_timeline(
    *, conn, topic: str, entity_slug: Optional[str] = None, limit: int = 20,
) -> list:
    """Return decision facts whose text matches `topic` (case-insensitive
    substring), most recent first. When entity_slug is provided, restricts
    to that entity (or NULL = cross-entity facts)."""
```

Returns a list of `{id, fact, entity_slug, created_at, supersedes_id}`. Empty list when no matches.

**New bot tool** `recall_decisions` registered in `goldman/bot/tools.py`:
- Input schema: `{topic: string, entity?: string}`.
- Calls `decision_timeline`, formats as a chronological text block.
- Example:
  ```
  Decision timeline for "VAT registration":
    2026-06-08: Hire UK accountant for VAT filings (amzg)
    2026-05-14: Defer UK VAT registration until £90k threshold (amzg)
  ```
- Empty case: `No prior decisions found matching "VAT registration".`

**Persona update** — `goldman/bot/handlers.py`'s `GOLDMAN_PERSONA`:
- One sentence: *"For 'what did we decide' questions or anything implying a structured timeline of prior decisions, prefer the `recall_decisions` tool over `recall` — it returns chronological decision-kind facts, not a similarity search."*

**API endpoint** `/v1/decisions` (POST):
- Body: `{topic: string, entity?: string}`.
- Returns `{decisions: [...]}` mirroring the function's return shape.
- Auth via the existing Bearer `GOLDMAN_API_KEY`.

**Plugin slash command** `/goldman:decisions <topic>`:
- Calls `/v1/decisions` with the topic.
- jq-renders the timeline.

## 3. What gets reused

- `goldman.facts_live` view (Phase 1) — already exists; restricts to the current head of each fact's supersedes chain.
- `goldman.entities` — for joining `entity_id` → slug.
- Existing `_HealthHandler._handle_api` plumbing (Phase 5) — routes /v1/decisions automatically once added to the dispatch.
- Existing plugin Bearer-token auth (Phase 5).

## 4. Search semantics

- **Match**: `fact ILIKE '%topic%'` — case-insensitive substring on the raw text of the fact. Simple, predictable, fast. Does NOT use embeddings.
- **Entity filter**: when `entity_slug` is provided, restrict to facts where `entity_id` matches that entity OR `entity_id IS NULL` (cross-entity facts apply to everyone).
- **Order**: `created_at DESC` (most recent first).
- **Limit**: 20 by default; configurable per call.

Out of scope for v1: stemming, synonyms, semantic similarity, topic auto-extraction.

## 5. Failure modes

| Situation | Behaviour |
|---|---|
| No facts match the topic | Function returns `[]`; bot tool returns `No prior decisions found matching "X".`; API returns `{"decisions": []}`. |
| Topic is empty / whitespace-only | API returns 400; bot tool returns clear error to Claude; function raises `ValueError`. |
| `entity_slug` doesn't exist | Entity-filter clause matches nothing; function returns `[]` (no error). |
| Fact's text contains the topic as a non-decision (kind != 'decision') | Excluded — function filters on `kind = 'decision'` explicitly. |
| Superseded facts | Not returned — `goldman.facts_live` already filters those out. |

## 6. Out of scope (v2+ if Liran wants)

- CLI command `cli.py decisions <topic>` — bot + plugin cover the surface; CLI is redundant for v1.
- Topic auto-grouping (multiple related decisions grouped under one topic header).
- Semantic / embedding-based matching.
- Decision provenance (which conversation turn or document the decision came from).
- Cross-supersedes chain display (showing the historical predecessors of each current decision).

## 7. Implementation tasks

| # | Task | Effort |
|---|---|---|
| 1 | `goldman/decisions.py` — `decision_timeline` (TDD) | 30 min |
| 2 | Bot tool `recall_decisions` + persona update | 20 min |
| 3 | API endpoint `/v1/decisions` + main.py route | 20 min |
| 4 | Plugin slash command `/goldman:decisions` | 10 min |
| 5 | Full regression + memory update | 5 min |

Total: ~1.5 hours of code work.

## 8. Open risks

| Risk | Mitigation |
|---|---|
| Substring search misses paraphrased decisions ("VAT decision" vs "tax registration choice") | v1 accepted limitation; if Liran reports misses we add semantic in v2. |
| Topic ambiguity (one word matches too much) | Liran picks more specific topics. The function's job is exact substring; smarter matching is v2. |
| Too many results returned | `limit=20` default; configurable per call. Future v2 can paginate. |

---

**Next step:** invoke `superpowers:writing-plans` to convert this spec into a step-by-step implementation plan.
