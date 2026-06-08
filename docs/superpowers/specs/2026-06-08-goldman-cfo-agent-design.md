# Goldman — CFO Agent Design

**Date:** 2026-06-08
**Author:** Liran Hamburg + Claude (brainstorm)
**Status:** Design, pre-implementation
**Repo:** `~/Desktop/Obsidian/Projects/zoho-invoice-agent` → rename to `goldman` in Phase 0
**Successor of:** the existing `zoho-invoice-agent` service (rename + evolve)

---

## 1. Goal

Evolve the existing single-purpose `zoho-invoice-agent` into **Goldman** — a multi-entity CFO, tax advisor, and business advisor for AMZ Expert Global Limited and its US subsidiary Specific Edge Outsourcing LLC.

Goldman has three hats, prioritised:

1. **Bookkeeper** — reads vendor bills from email, files them in Zoho (correct entity), backs up to Google Drive, creates client invoices on command, alerts on overdue items.
2. **Tax advisor** — knows the company's jurisdictions, registrations, and prior advisor decisions. Answers tax questions grounded in *this* company's setup, not generic.
3. **Business advisor** — has the full history. Every contract, every prior decision, every conversation, retrievable verbatim with source citations.

**Bookkeeper ships first (Phases 0–5). Advisor depth is Phase 6, an ongoing layer.**

## 2. Identity & guardrails

**Persona.** Goldman is the CFO of AMZ Expert Global Limited (Hong Kong, parent) and Specific Edge Outsourcing LLC (US, subsidiary).

**Voice.** Conservative, precise, plain English. Cites sources. Says "I don't know" when he doesn't. Flags risk explicitly.

**Hard guardrails (Goldman will never):**
- Move money.
- Sign or send a contract.
- File a tax return.
- Delete a `goldman_*` row or document.

Goldman drafts, recommends, alerts, prepares. Liran executes.

## 3. Architecture — one Python service, three front doors

```
                    ┌─────────────────────────────────┐
                    │   goldman/  (Python package)    │
                    │                                 │
                    │  brain.py      — company KB API │
                    │  zoho/         — multi-entity   │
                    │  bills/        — vendor email   │
                    │  invoices/     — client billing │
                    │  documents/    — store + extract│
                    │  conversations/— history + recall│
                    │  drive/        — Google Drive   │
                    │  tax/          — jurisdiction   │
                    │  tools.py      — LLM tool registry│
                    └─────────────────────────────────┘
                         ▲           ▲          ▲
                         │           │          │
              ┌──────────┘           │          └──────────┐
              │                      │                     │
      ┌───────────────┐     ┌────────────────┐    ┌────────────────┐
      │ Telegram bot  │     │  CLI            │    │ Claude Code    │
      │ @GoldmanCFO_  │     │  python cli.py  │    │ plugin/skill   │
      │ bot           │     │                 │    │ (Cowork-grade) │
      └───────────────┘     └────────────────┘    └────────────────┘
                         (all three call the same Goldman library)
```

One codebase. Three front doors. Shared brain. A fact learned via Telegram is immediately available in Claude Code.

**Why this shape (Approach A from brainstorm):** one source of truth for behaviour; bug fixes propagate to every surface; preserves the working code in the existing repo; minimal refactor cost.

## 4. Repo strategy — rename and evolve in place

- Rename `~/Desktop/Obsidian/Projects/zoho-invoice-agent` → `goldman`.
- Rename the Render service `zoho-invoice-agent` → `goldman`. URL changes (acceptable — only used internally + by webhooks we control).
- All existing modules survive: `zoho/`, `wise/`, `gmail/`, `telegram/`, `scheduler/`, `batch/`. They get refactored, not rewritten.
- New top-level modules: `brain/`, `documents/`, `drive/`, `conversations/`, `tax/`, `goldman_db/` (Supabase client).

## 5. Multi-entity data model

Goldman is multi-tenant by entity from day one. Every operation, every row, every API call carries an `entity_id`.

### 5.1 Entities

```
entities
├── id (uuid, pk)
├── slug (text, unique) — e.g. "amzg", "seo"
├── legal_name (text) — "AMZ Expert Global Limited" / "Specific Edge Outsourcing LLC"
├── jurisdiction (text) — "HK" / "US"
├── parent_entity_id (uuid, fk → entities.id, nullable)
├── company_number (text)
├── incorporation_date (date)
├── registered_address (text)
├── fiscal_year_end (date) — MM-DD
├── base_currency (text) — "HKD" / "USD"
├── zoho_organization_id (text)
├── zoho_credential_key (text) — env var prefix (ZOHO_AMZG_*, ZOHO_SEO_*)
└── created_at, updated_at
```

Seed rows on Phase 0:

| slug | legal_name | jurisdiction | parent | zoho_org |
|---|---|---|---|---|
| `amzg` | AMZ Expert Global Limited | HK | — | (existing) |
| `seo` | Specific Edge Outsourcing LLC | US | `amzg` | (new creds) |

### 5.2 Supporting tables

All carry `entity_id` (fk → entities.id). Cross-entity rows carry both with a join table.

- **`tax_registrations`** — one row per (entity × tax × jurisdiction). Fields: `tax_type` (VAT/sales_tax/profits_tax/withholding), `jurisdiction`, `registration_number`, `effective_from`, `effective_to` (nullable, never set to "expired" — append a new row), `filing_cadence`, `notes`.
- **`clients`** — synced from Zoho contacts, scoped to entity. Enriched: `tier`, `primary_contact`, `notes`.
- **`vendors`** — synced from Zoho contacts + recurring-expense detection. Enriched: `category` (hosting/factory/shipping/software/professional_services/utilities/other), `typical_amount`, `typical_cadence`, `always_confirm` (bool), `last_seen_at`.
- **`bank_accounts`** — `provider` (Wise/HSBC/etc.), `currency`, `last_balance`, `last_balance_at` (manual v1; live sync Phase 6).

### 5.3 Multi-Zoho client factory

The current single-Zoho client gets refactored:

```python
# Before
client = ZohoClient(auth, api_base_url, organization_id)

# After
client = goldman.zoho.for_entity("amzg")  # returns a fully wired ZohoClient
                                           # for AMZ Expert Global Limited
```

The factory:
- Reads credentials from env keyed by `entity.zoho_credential_key` (e.g. `ZOHO_AMZG_REFRESH_TOKEN`, `ZOHO_AMZG_ORG_ID`).
- Caches one `ZohoClient` per entity per process.
- Refuses to operate on a Zoho org that doesn't match the entity in any cross-table call.

Every existing call site (`InvoiceService`, `ContactService`, `ItemService`) takes `entity_slug` as a parameter — no more "default Zoho".

## 6. Memory system — append-only, immutable, traceable

Liran's principle (recorded for posterity):

> Unlike HQ Hub, Goldman has low conversation volume and very high data sensitivity. He saves everything, every conversation, every document, exactly as is, and makes it retraceable. Data lives forever.

### 6.1 Layers

| Layer | Table(s) | What it does |
|---|---|---|
| **Conversation log** | `goldman_conversation_turns` | Every message ever, every front-door, full text + role + `entity_id` + timestamp. Embedded for semantic search. Never compressed. |
| **Facts (append-only)** | `goldman_facts` | Structured truths. `kind ∈ {target, preference, constraint, commitment, event, decision}`. Corrections never overwrite — new rows supersede old ones via `supersedes_id` + timestamp. `content_hash` for dedup. Embedded. |
| **Documents** | `goldman_documents` + `goldman_document_chunks` | Original file kept in Supabase Storage. Chunked + embedded. Original is one click away from any retrieval. |
| **Capabilities registry** | `goldman_capabilities` | Developer-curated. What Goldman can DO (tools, skills, jurisdictions). Distinct from learned knowledge. |

### 6.2 What is explicitly NOT included (intentional omissions vs Atlas)

- ❌ `session_summaries` — no lossy summarisation. Sensitivity > token efficiency.
- ❌ `decay-memory` cron — nothing expires.
- ❌ `expires_at`, `archived_at`, `pinned` columns — incompatible with append-only.
- ❌ `valid_until` on facts — corrections happen via `supersedes_id`, original row preserved.

### 6.3 Retrieval — hybrid search

Same RRF pattern as Atlas, adapted:

1. Embed the question (OpenAI `text-embedding-3-small`, 1536-d).
2. **Vector search** across facts + conversation turns + document chunks, filtered by `entity_id` (or NULL for cross-entity).
3. **Keyword search** (Postgres FTS) over the same.
4. **Fuse via Reciprocal Rank Fusion**, cap by token budget.
5. **Inject active facts** as system context (entity registrations, fiscal year, ownership).
6. Send to Claude with conversation history + retrieved memory.

Every returned result carries a **source pointer** (turn ID + timestamp + front-door, or document ID + page + chunk). Every Goldman answer cites its sources.

### 6.4 Maintenance crons (Supabase pg_cron)

Only the **lossless** subset of Atlas's pattern:

- `goldman-embed-pending` — embeds new turns / facts / chunks. Frequent (every 5 min).
- `goldman-dedup-on-write` — `content_hash` check; identical fact bumps `seen_count` instead of inserting noise.
- `goldman-conflict-check` — when a new fact contradicts an active one, flag both with `conflict_with[]` so Goldman can ask Liran to resolve. **Neither row is deleted.** Resolution = new fact with `supersedes_id`.

### 6.5 Schema isolation defenses (key architectural choice)

Goldman shares the HQ Hub Supabase project (`tjxngrplgiqicdorsjzr`) for operational simplicity, but is architecturally isolated:

- All Goldman tables live in a dedicated **`goldman` Postgres schema** (not just a table prefix — actual `CREATE SCHEMA goldman`).
- A dedicated **`goldman_app` Postgres role** with `USAGE` on `goldman` schema only; `REVOKE ALL` on `public.*`. Goldman code authenticates as this role.
- Storage buckets are dedicated and named: `goldman-bills`, `goldman-documents`. RLS scoped to `goldman_app`.
- Edge functions for Goldman have a runtime guard: any DB query referencing non-`goldman.*` tables raises immediately.
- A separate `goldman_admin` role for migrations; only Liran's local dev + CI use it.

This gives Goldman blast-radius isolation without standing up a second Supabase project.

## 7. Vendor intake pipeline — the three-write path

For every parsed bill, Goldman writes to **three places** in this exact order, with idempotency and partial-write recovery.

### 7.1 The pipeline

```
Vendor email arrives (Gmail label or forward to bills@...)
or photo uploaded on Telegram
       │
       ▼
PARSE — Claude with vision extracts:
  vendor, invoice_no, date, amount, currency,
  line_items, tax, due_date, billing_entity
       │
       ▼
MATCH:
  • billing_entity → entities row (amzg or seo)
  • vendor → vendors row (fuzzy match on name + email domain)
  • idempotency_hash = sha256(vendor_norm + invoice_no + amount + date)
  • duplicate? → skip all writes, notify "already filed (ref)"
       │
       ▼
TRUST GATE:
  AUTO-FILE if:
    – known vendor (vendors.seen_count ≥ 3)
    – amount within ±15% of vendors.typical_amount
    – amount ≤ $500
    – billing_entity unambiguous
  CONFIRM-FIRST otherwise → Telegram inline keyboard:
    [✓ File to HK]  [✓ File to US]  [✗ Hold]
       │
       ▼
WRITE 1 — Supabase Storage (Goldman's vault)
  bills/{entity_slug}/{YYYY}/{MM}/{vendor_slug}_{invoice_no}.pdf
  + goldman_documents row {idempotency_hash, in_storage=true}
       │
       ▼
WRITE 2 — Google Drive (human backup, Shared Drive)
  {entity_legal_name} / {YYYY} / {Month name} / {original_filename}
  + goldman_documents.in_drive = true
       │
       ▼
WRITE 3 — Zoho Expenses (the ledger)
  POST /expenses → create expense in entity's Zoho org
  POST /expenses/{id}/attachment → attach original PDF
  + goldman_documents.in_zoho = true, zoho_expense_id stored
       │
       ▼
NOTIFY — Telegram:
  "Filed Helium 10 $89 → AMZ Expert Global (HK).
   Zoho expense E-1042. Drive link."
```

### 7.2 Trust gate rules

Auto-file requires **all** of:

1. Vendor exists in `vendors` with `seen_count ≥ 3`.
2. Amount within ±15% of `vendors.typical_amount`.
3. Amount ≤ $500 absolute ceiling.
4. `billing_entity` parsed with high confidence (exact match to a known entity legal name or DBA on the bill).
5. `vendors.always_confirm = false`.
6. Not a duplicate (idempotency hash check).

Any failure → Telegram confirm with parsed details and action buttons.

### 7.3 Partial-write recovery

`goldman_documents` carries three booleans: `in_storage`, `in_drive`, `in_zoho`, plus `last_write_attempt_at` and `last_error`. If any write fails:

- The row exists with `status = "partial"`.
- `goldman-retry-writes` cron retries failed legs every 30 min for 24 h, then 4 h thereafter.
- `goldman status` and Telegram digest surface anything stuck > 24 h.
- The **original PDF is always in Supabase Storage** first, so nothing is ever lost.

### 7.4 Drive folder structure (exact)

Top-level Shared Drive: `Goldman Bills`.

```
Goldman Bills/
├── AMZ Expert Global Limited/
│   ├── 2026/
│   │   └── June/
│   │       ├── Helium 10 - Invoice C0C735E-0091.pdf
│   │       └── Wix - Domain Yearly Invoice.pdf
│   └── 2025/
└── Specific Edge Outsourcing LLC/
    └── 2026/
        └── June/
            └── Stripe Receipt 2026-06-04.pdf
```

Year and month derive from the **invoice date**, not the email-received date. Folders are find-or-create (never duplicated).

## 8. Front doors

### 8.1 Telegram bot — `@GoldmanCFO_bot`

- Separate bot from Bob. Separate chat.
- Conversation router uses Claude with the Goldman tool registry.
- Tools: `file_bill`, `create_invoice`, `list_overdue`, `recall`, `status`, `who`, `remember`, `explain`.
- Every turn logged into `goldman_conversation_turns` with `entity_id` context (inferred or asked).
- File / photo / forwarded-email upload routes to the vendor intake pipeline.
- Proactive messages: trust-gate confirmations, partial-write retries, Phase 6 anomalies.
- Deployed alongside the Python service on Render (same process, separate poller thread).

### 8.2 Claude Code plugin — `goldman.plugin`

- Installable Claude Code plugin (`/plugin install goldman`).
- Skills exposed: `/goldman:invoice`, `/goldman:bill`, `/goldman:status`, `/goldman:recall`, `/goldman:explain`, `/goldman:remember`, `/goldman:who`.
- Each skill calls Goldman's HTTP API on Render (`https://goldman.onrender.com/v1/*`).
- Works in any Claude session — terminal, Cowork, mobile Claude.
- Same brain as Telegram bot (shared `goldman` schema).
- Authentication: API key in plugin config; one key per Liran's session pool.

### 8.3 CLI — stays as-is

- `python cli.py invoice|bill|status|recall|onboard|...`
- Used for scripting, debugging, and initial onboarding (see §10).
- Same tool registry under the hood as Telegram + Claude Code.

## 9. Onboarding flow — brain dump first, gap fill second

Phase 1 facts that only Liran knows (registrations, ownership %, bank accounts, vendor categorisations, prior decisions) get into Goldman via a **two-step conversational onboarding**:

### Step 1 — brain dump

Liran runs `python cli.py onboard` (or `/goldman:onboard` later). The CLI opens `$EDITOR` (or accepts piped stdin) for him to **paste a single multi-paragraph dump** of everything he already has prepared. No structured form.

### Step 2 — Claude parses

Goldman sends the dump to Claude with an extraction prompt. Claude returns structured JSON across the schema: entities, tax_registrations, clients, vendors, bank_accounts, and free-floating facts. Goldman stores everything as:

- Schema rows where the data fits a structured table (e.g. tax_registration with reg_number, jurisdiction, cadence).
- `goldman_facts` rows with `source = user_explicit` for things that don't fit a table (e.g. "we use a Hong Kong CPA called X").
- `goldman_documents` rows for any URLs / filenames mentioned.

### Step 3 — gap audit

Goldman runs a coverage check — a hard-coded list of facts he must know:
- Each entity has at least one `tax_registration` for its primary tax (HK profits, US federal income, sales tax nexus).
- Each entity has at least one `bank_account`.
- Each entity has a `fiscal_year_end`.
- Each entity has a `registered_address`.
- (Plus 10–15 more.)

For each missing fact, Goldman asks one targeted question in the terminal:
> *"I don't have a fiscal year end for Specific Edge Outsourcing LLC. What's its fiscal year-end date? (MM-DD)"*

One question at a time. Liran can answer `skip` and Goldman defers.

### Step 4 — confirmation summary

Goldman prints a `who` view of what he learned, asks Liran to confirm or correct anything before committing as durable facts.

## 10. Build phases

| Phase | Deliverable | Estimate |
|---|---|---|
| **0 — Foundation** | Rename repo + Render service, multi-entity Zoho factory, new HK + US creds wired, `goldman` schema created with isolation, no behaviour regressions. | 1–2 days |
| **1 — Company brain v1** | `entities` (seeded), `tax_registrations`, `clients` (synced), `vendors` (synced), `bank_accounts`. Onboarding flow (§9). `goldman who` command. | 2–3 days |
| **2 — Memory & documents** | `goldman_conversation_turns`, `goldman_facts`, `goldman_documents` + chunks, `goldman_capabilities`. pgvector setup. Hybrid retrieval RPC. `remember` + `recall` commands. | 3–4 days |
| **3 — Vendor intake pipeline** | Generalised Gmail watcher (per-entity labels). Claude-vision parser. Three-write pipeline. Trust gate. Telegram inline confirmations. Failure tray + retry cron. | 3–5 days |
| **4 — Telegram bot** | `@GoldmanCFO_bot`. Conversation router. Tool registry. File/photo upload → intake. Conversation logging. Proactive trust-gate + partial-write messages. | 3–5 days |
| **5 — Claude Code plugin** | `goldman.plugin` for Claude Code marketplace. Skills `/goldman:*`. HTTP API on Render. Auth. Installable in Cowork. | 3–4 days |
| **6 — Advisor depth** | Ongoing: tax-jurisdiction knowledge packs, anomaly detection, monthly digest, cross-entity insights, decision recall. Each addition gets its own short brainstorm. | ongoing |

**Bookkeeper-grade Goldman ships at end of Phase 5: ~3 weeks of focused work.**

After Phase 5 there's an explicit **stop-and-decide** point. Run Goldman for a quarter, then decide if Phase 6 advisor depth is worth the extra work.

## 11. Defaults (override any of these in implementation)

- **Email intake:** label-based on Liran's primary Gmail (`Goldman/bills`, `/HK`, `/US`). Dedicated `bills@…` address deferred.
- **Embeddings:** OpenAI `text-embedding-3-small`. Same toolchain as Atlas.
- **Trust gate thresholds:** ±15% of vendor trailing average **AND** ≤ $500 absolute. Either failed → confirm first.
- **Zoho API:** `Expenses` endpoint (not `Bills`). Original PDF attached to each expense.
- **Currency:** Goldman doesn't convert. Foreign-currency invoices: store both source and entity base currency, let Zoho handle the conversion.
- **Accounting basis:** cash basis for v1. Switch to accrual is a Phase 6 conversation.
- **Wise:** existing direct-API webhook flow stays untouched. Wise balance pull for cash position is Phase 6.
- **Document chunking:** 512 tokens per chunk, 64-token overlap. PDFs OCR'd via Claude vision (no separate OCR pipeline for v1).

## 12. Out of scope (v1)

- Stripe, PayPal, Shopify, Amazon Seller Central revenue ingestion (Phase 6+).
- Payroll, contractor 1099 management (Phase 6).
- Direct bank-account aggregation (Plaid / Open Banking) — manual balance entry only in v1.
- Replacing the accountant. Goldman drafts and prepares; Liran's CPA reviews and files.
- Multi-user / team access. Liran is the sole user; auth is single-tenant.

## 13. Open risks

| Risk | Mitigation |
|---|---|
| Claude vision misreads a vendor invoice → wrong amount filed in Zoho | Trust gate ($500 ceiling). Telegram confirmation for anything above. Original PDF always retrievable from Supabase Storage for audit. |
| Goldman files to the wrong entity (HK vs US) | `billing_entity` must match a known entity legal name / DBA before auto-file. Ambiguous → Telegram confirm. |
| OpenAI embedding API outage | Embeddings queue (`goldman-embed-pending`) — non-urgent retrieval still works via keyword FTS until embeddings catch up. |
| Schema isolation accidentally broken (Goldman code touches `public.*`) | Postgres role `goldman_app` has `REVOKE ALL` on `public.*` — failure is hard, not silent. CI checks. |
| HQ Hub migration changes break Goldman | All Goldman tables in dedicated `goldman` schema, separate migration directory. No cross-schema FKs. |
| Vendor invoice in a language Claude vision misreads (e.g. Chinese factory invoices) | Confidence threshold; low-confidence parses go to Telegram confirm with side-by-side image + extracted fields. |
| Conversation turn count grows unbounded over years | Append-only is intentional. Volume is low (CFO-grade, not chat-bot). At 100 turns/month × 10 years = 12k rows. Trivial. |

## 14. Naming conventions

- **Code namespace:** `goldman.*` (Python package), `goldman.*` (Postgres schema), `goldman-*` (Supabase Storage buckets), `goldman.plugin` (Claude Code).
- **Telegram bot:** `@GoldmanCFO_bot`.
- **Render service:** `goldman`.
- **Drive top folder:** `Goldman Bills`.
- **Entity slugs:** `amzg` (AMZ Expert Global Limited), `seo` (Specific Edge Outsourcing LLC).
- **Env var convention:** `ZOHO_{ENTITY_SLUG_UPPER}_*`. E.g. `ZOHO_AMZG_REFRESH_TOKEN`, `ZOHO_SEO_ORG_ID`.

---

**Next step after this spec is approved:** invoke `superpowers:writing-plans` to produce the implementation plan for Phase 0, with subsequent phases planned as separate cycles.
