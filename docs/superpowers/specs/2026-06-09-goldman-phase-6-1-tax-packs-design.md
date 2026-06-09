# Goldman Phase 6.1 — Tax-Jurisdiction Knowledge Packs (v1: US LLC tax)

**Date:** 2026-06-09
**Author:** Liran Hamburg + Claude (brainstorm)
**Status:** Design, pre-implementation
**Scope:** First piece of Phase 6 advisor depth. Future packs (HK profits tax, transfer pricing, etc.) get their own short brainstorms.

---

## 1. Goal

Give Goldman the US federal tax rules for foreign-owned single-member LLCs as retrievable reference material. When Liran asks a US-LLC tax question, Goldman cites the canonical pack rules alongside Liran's own accountant letters — the rule is one source, his specific advice is another, both shown together.

## 2. What gets built (minimum footprint)

**Schema** — one migration, additive only:

```sql
ALTER TABLE goldman.documents
    DROP CONSTRAINT goldman_documents_source_check,
    ADD CONSTRAINT goldman_documents_source_check
        CHECK (source IN ('uploaded', 'email', 'manual', 'knowledge_pack')),
    ADD COLUMN IF NOT EXISTS pack_topic   TEXT,
    ADD COLUMN IF NOT EXISTS pack_version TEXT;

CREATE INDEX IF NOT EXISTS idx_goldman_documents_pack_topic
    ON goldman.documents(pack_topic)
    WHERE pack_topic IS NOT NULL;
```

**Pack file** — `knowledge_packs/us_llc_tax_v1.md` checked into git. Nine H2 sections (see §4 below).

**CLI command** — `python3 cli.py pack add FILE --topic TOPIC --version VERSION`. Wraps `upload_document` (no new ingestion pipeline). Sets the three new document fields.

**Goldman persona update** — one paragraph added to:
- `goldman/bot/handlers.py` → `GOLDMAN_PERSONA` constant
- `goldman.plugin/commands/explain.md` synthesis step

The paragraph: *"When retrieved chunks have `source = 'knowledge_pack'`, cite them as 'per the [pack_topic] reference pack v[pack_version]'. When chunks come from uploaded documents (your accountant's letters, contracts), cite them as 'per [filename]'. Show both kinds together when both are relevant — the pack is the rule, the letters are the specifics."*

That's the full surface area. Nothing else changes.

## 3. What gets reused (no new infrastructure)

- `upload_document` (Phase 2) — handles the storage + chunking + summarisation
- `goldman.documents` + `goldman.document_chunks` tables (Phase 2)
- Tiktoken chunker, 512-token windows + 64-token overlap (Phase 2)
- OpenAI embeddings pipeline (Phase 2 — runs on next `db embed-pending`)
- `hybrid_search` RPC (Phase 2 — already returns chunks regardless of source)
- Claude Haiku summariser (Phase 2 — generates the 2-sentence summary)
- Telegram bot agent + tool registry (Phase 4 — `recall` tool gets the new chunks automatically)
- Claude Code plugin `/goldman:recall` and `/goldman:explain` (Phase 5 — same)

## 4. Pack content (`knowledge_packs/us_llc_tax_v1.md`)

Nine H2 sections, structured for clean chunk boundaries. Target ~6,000–10,000 words; ~20–40 chunks at 512 tokens with 64 overlap.

1. **Entity classification** — Default IRS treatment of a foreign-owned single-member LLC (disregarded entity for income tax, separate for employment + excise). When and why to elect corporate treatment via Form 8832.
2. **Form 5472 + pro forma 1120** — The single biggest landmine. $0 threshold (any reportable transaction triggers filing). $25k auto-imposed penalty for late or missed filings. Due dates. What counts as a reportable transaction with the foreign owner.
3. **Federal income tax basics** — Effectively Connected Income (ECI) concept. When a disregarded-entity LLC actually generates US-source income vs. not. 1040-NR implications for the foreign owner.
4. **State tax considerations** — Delaware franchise tax for Delaware LLCs (the common formation state, flat fee). Sales-tax nexus brief (marketplace facilitator rules cover most Amazon sellers). State income tax for foreign-owned LLCs.
5. **Filing calendar** — Annual deadlines that matter: Form 5472 + pro forma 1120 (April 15 typically, extendable). State franchise tax dates. Annual report dates by state.
6. **EIN / ITIN / SSN** — Who needs what. EIN is mandatory for any LLC. ITIN for foreign owners without SSN. How to get each (Form SS-4 for EIN, Form W-7 for ITIN).
7. **Withholding obligations** — 1042 / 1042-S when the LLC pays non-US persons (intercompany services to the HK parent, contractor payments to non-US contractors). 30% default withholding; treaty rates where applicable.
8. **Contractor vs employee classification** — 1099-NEC vs W-2. Why misclassification triggers back taxes + penalties. IRS factors (behavioral control, financial control, relationship type). Particular relevance for a services LLC.
9. **Common penalty triggers** — Late or missed 5472, undisclosed foreign accounts (FBAR + Form 8938), ECI mischaracterisation, payroll tax delinquencies. What gets audits and what gets the $10k+ penalties.

Each H2 section is self-contained reference content (no narrative across sections). Citation-friendly: chunks within a section make sense standalone.

## 5. Review + ingestion loop

1. Claude (me) writes `knowledge_packs/us_llc_tax_v1.md` from training data — sourced from publicly available IRS guidance and standard CPA references. Conservative: only includes well-established rules, flags ambiguity where present.
2. Liran reads top-to-bottom, edits anything inaccurate to his actual setup, commits the edited file.
3. Liran runs `python3 cli.py pack add knowledge_packs/us_llc_tax_v1.md --topic us_llc_tax --version v1-2026-06`.
4. Liran runs `python3 cli.py db embed-pending` to vectorise the chunks.
5. Sanity check: Liran asks Goldman a covered question via Telegram or `/goldman:recall`. Goldman cites the pack with version.

## 6. Updates later (out of scope for v1)

When US tax law changes meaningfully (or Liran wants a refresh), the flow repeats: I draft `us_llc_tax_v2.md`, Liran reviews, runs `pack add --version v2-2027-04`.

Both versions live in `goldman.documents`. The `hybrid_search` RPC retrieves chunks from whichever is most semantically relevant. Goldman cites the version in his answer, so Liran sees "per us_llc_tax v1-2026-06..." and knows if it's old.

**Multi-version filtering** (e.g. auto-archive old versions, or prefer newer versions in retrieval) is not in this spec. If duplicate-citation noise becomes a real problem, Phase 6.1.1 adds an `is_archived` flag and a `WHERE NOT is_archived` clause to the RPC.

## 7. Out of scope

- Other tax packs (HK profits tax, UK VAT, transfer pricing HK↔US, US sales tax deep-dive) — each gets its own short brainstorm.
- Automated pack refresh (cron, news scraping, etc.) — manual `pack add` is fine for slow-changing reference material.
- A web UI for editing packs — Markdown + git diff is the editing surface.
- Pack search beyond hybrid_search — no separate "pack-only" query mode. If users want pack-only results, future filter param on hybrid_search.
- Multi-language packs — English only.

## 8. Implementation phases

| # | Task | Effort |
|---|---|---|
| 1 | Schema migration 0019 (ALTER goldman.documents) + apply live | 30 min |
| 2 | CLI `pack add` command (~30 LOC wrapping upload_document) | 1 hr |
| 3 | Goldman persona + plugin prompt updates | 30 min |
| 4 | Draft `knowledge_packs/us_llc_tax_v1.md` (the actual content) | 2–3 hr |
| 5 | Liran review + edit | (Liran's time) |
| 6 | Ingest + live smoke test (ask Goldman a covered question) | 15 min |

**Goldman-side build:** ~half a day. **Liran review:** as long as it takes him to read 6,000 words and edit anything wrong.

## 9. Open risks

| Risk | Mitigation |
|---|---|
| Pack content is wrong or out of date when I draft it | Liran review is mandatory before `pack add`. The pack is reference material, not autopilot. |
| Goldman cites pack chunks too aggressively, ignoring Liran's actual letters | Persona prompt explicitly says "show both kinds together when both are relevant." Smoke test verifies this. |
| Pack ingestion fails because Storage / OpenAI keys still aren't set | Same as Phases 2–5: graceful config errors, nothing changes about the ingestion path. Liran needs the same env vars he already needs for `document upload`. |
| Pack covers something inapplicable to Liran's actual setup (e.g. multi-member rules when he has a single-member LLC) | Liran's review step catches this. Pack v1 explicitly written for single-member foreign-owned LLC. |
| Future pack versions overwhelm retrieval noise | Mitigation deferred (§6). If it actually becomes a problem, we add archiving. |

---

**Next step:** invoke `superpowers:writing-plans` to convert this spec into a step-by-step implementation plan.
