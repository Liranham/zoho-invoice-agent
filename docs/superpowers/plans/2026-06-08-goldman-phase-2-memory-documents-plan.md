# Goldman Phase 2 — Memory & Documents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Goldman gains long-term memory. Append-only conversation log + documents + chunks; embedding pipeline (OpenAI 1536d); hybrid retrieval (vector + keyword via RRF) filtered per entity; capabilities registry; CLI commands for remember/recall/document upload. Foundation for Phase 3 (vendor intake) and Phase 4 (Telegram conversation).

**Architecture:** Continue Phase 1's pattern — one table per concern, one repository per table, TDD per repository. Three new producer tables (`conversation_turns`, `documents`, `document_chunks`), one new metadata table (`capabilities`), two columns ALTERed onto `facts` (embedding + conflict_with), and one Postgres function (`goldman.hybrid_search`). Embeddings via OpenAI `text-embedding-3-small` (1536d, same as Atlas). Document text stored in Supabase Storage (service-role HTTP API); chunks + embeddings in Postgres. Document summaries via `claude-haiku-4-5-20251001` for cost. Hybrid retrieval is pure SQL (RRF fusion across vector + full-text), callable from any front door (CLI/Telegram/Claude Code).

**Tech Stack:** Python 3.9+, new deps `openai>=1.0`, `tiktoken>=0.7`, `pypdf>=4.0`, `requests` (already present). Existing `anthropic`, `psycopg`, `click`, `pytest`, `python-dotenv`. Postgres with pgvector (already enabled in `public` schema of HQ Hub Supabase project). OpenAI `text-embedding-3-small` (1536d). Anthropic `claude-haiku-4-5-20251001` for doc summarisation.

---

## File Map

**Create:**
- `migrations/0009_facts_embedding.sql` — ALTER goldman.facts add embedding + conflict_with.
- `migrations/0010_conversation_turns.sql` — `goldman.conversation_turns` table.
- `migrations/0011_documents.sql` — `goldman.documents` + `goldman.document_chunks` tables.
- `migrations/0012_capabilities.sql` — `goldman.capabilities` table.
- `migrations/0013_hybrid_search.sql` — `goldman.hybrid_search()` function.
- `migrations/0014_storage_bucket.sql` — register `goldman-documents` bucket.
- `migrations/0015_seed_capabilities.sql` — initial capability rows.
- `goldman_db/conversation_turns.py` — `ConversationTurn` dataclass + `ConversationTurnRepository`.
- `goldman_db/documents.py` — `Document` + `DocumentChunk` dataclasses + `DocumentRepository` + `DocumentChunkRepository`.
- `goldman_db/capabilities.py` — `Capability` + `CapabilityRepository`.
- `goldman_db/hybrid_search.py` — `HybridSearchResult` + `hybrid_search(conn, ...)` wrapper.
- `goldman/embeddings.py` — `EmbeddingClient` wrapping OpenAI; `embed_pending_in(conn)` batch worker.
- `goldman/chunker.py` — `chunk_text(text, max_tokens, overlap)` using tiktoken.
- `goldman/storage.py` — `SupabaseStorage` wrapper (upload/download via service-role HTTP).
- `goldman/documents.py` — high-level `upload_document(...)` flow (storage + summarise + chunk + insert).
- `tests/test_goldman_conversation_turns_repo.py`
- `tests/test_goldman_documents_repo.py`
- `tests/test_goldman_capabilities_repo.py`
- `tests/test_goldman_hybrid_search.py`
- `tests/test_goldman_embeddings.py`
- `tests/test_goldman_chunker.py`
- `tests/test_goldman_storage.py`
- `tests/test_goldman_documents_upload.py`

**Modify:**
- `requirements.txt` — add `openai>=1.0`, `tiktoken>=0.7`, `pypdf>=4.0`.
- `goldman_db/facts.py` — add `list_pending_embedding`, `set_embedding`, `find_potential_conflicts`, `mark_conflict`.
- `tests/test_goldman_facts_repo.py` — add tests for the new methods.
- `cli.py` — add `remember`, `recall`, `document upload`, `document list`, `db embed-pending` commands.
- `.env.example` — add `OPENAI_API_KEY`, `GOLDMAN_SUPABASE_URL`, `GOLDMAN_SUPABASE_SERVICE_KEY`.

---

## Task 1: Add embedding / chunking / PDF dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Append to requirements.txt**

```
openai>=1.0.0
tiktoken>=0.7.0
pypdf>=4.0.0
```

- [ ] **Step 2: Install + verify**

```bash
python3 -m pip install --user -r requirements.txt 2>&1 | tail -5 && \
python3 -c "import openai, tiktoken, pypdf; print('openai', openai.__version__, '| tiktoken', tiktoken.__version__, '| pypdf', pypdf.__version__)"
```

Expected: prints versions, no ImportError.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "Add openai/tiktoken/pypdf for Goldman embedding + chunking + PDF

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Migration 0009 — ALTER goldman.facts (embedding + conflict_with)

**Files:**
- Create: `migrations/0009_facts_embedding.sql`

pgvector is already enabled in the `public` schema of the HQ Hub Supabase project — verified by Phase 0 isolation test. The `vector` type is usable by `goldman_app_login` without additional grants.

- [ ] **Step 1: Write the SQL**

Create `migrations/0009_facts_embedding.sql`:

```sql
-- Phase 2: add embedding + conflict tracking to goldman.facts.
-- pgvector extension lives in public; vector type is usable without extra grants.

ALTER TABLE goldman.facts
    ADD COLUMN IF NOT EXISTS embedding vector(1536),
    ADD COLUMN IF NOT EXISTS conflict_with UUID[] NOT NULL DEFAULT '{}';

-- ivfflat index for ANN. Empty table -> we still create it; it adapts as data grows.
CREATE INDEX IF NOT EXISTS idx_goldman_facts_embedding
    ON goldman.facts USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

-- Full-text search index for the keyword leg of hybrid search.
CREATE INDEX IF NOT EXISTS idx_goldman_facts_fts
    ON goldman.facts USING gin (to_tsvector('english', fact));
```

- [ ] **Step 2: Smoke-check + Commit**

```bash
python3 -c "
from pathlib import Path
sql = Path('migrations/0009_facts_embedding.sql').read_text()
assert 'ADD COLUMN IF NOT EXISTS embedding vector(1536)' in sql
assert 'ADD COLUMN IF NOT EXISTS conflict_with' in sql
assert 'idx_goldman_facts_embedding' in sql
print('OK')
" && git add migrations/0009_facts_embedding.sql && git commit -m "Add migration 0009: facts.embedding + conflict_with + indexes

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Migration 0010 — goldman.conversation_turns

**Files:**
- Create: `migrations/0010_conversation_turns.sql`

- [ ] **Step 1: Write the SQL**

Create `migrations/0010_conversation_turns.sql`:

```sql
-- Goldman conversation turns: append-only log of every Goldman ↔ user exchange.
-- Per spec §6.1 — verbatim, never compressed, never deleted.

CREATE TABLE IF NOT EXISTS goldman.conversation_turns (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id    UUID         REFERENCES goldman.entities(id),  -- nullable for cross-entity
    session_id   TEXT         NOT NULL,                          -- caller-generated
    front_door   TEXT         NOT NULL CHECK (front_door IN ('cli', 'telegram', 'claude_code')),
    role         TEXT         NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    text         TEXT         NOT NULL,
    embedding    vector(1536),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_goldman_turns_entity_session
    ON goldman.conversation_turns(entity_id, session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_goldman_turns_embedding
    ON goldman.conversation_turns USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);
CREATE INDEX IF NOT EXISTS idx_goldman_turns_fts
    ON goldman.conversation_turns USING gin (to_tsvector('english', text));

COMMENT ON TABLE goldman.conversation_turns IS
    'Append-only. Verbatim turn-by-turn log. No UPDATE/DELETE.';
```

- [ ] **Step 2: Verify + Commit**

```bash
python3 -c "
from pathlib import Path
sql = Path('migrations/0010_conversation_turns.sql').read_text()
assert 'CREATE TABLE IF NOT EXISTS goldman.conversation_turns' in sql
assert 'embedding vector(1536)' in sql
assert 'front_door' in sql
print('OK')
" && git add migrations/0010_conversation_turns.sql && git commit -m "Add migration 0010: goldman.conversation_turns (append-only)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Migration 0011 — goldman.documents + chunks

**Files:**
- Create: `migrations/0011_documents.sql`

- [ ] **Step 1: Write the SQL**

Create `migrations/0011_documents.sql`:

```sql
-- Goldman documents: every contract, tax filing, advisor letter.
-- Original kept in Supabase Storage (bucket: goldman-documents).
-- Chunks + embeddings live in Postgres.
-- Per spec §6.1.

CREATE TABLE IF NOT EXISTS goldman.documents (
    id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id             UUID         REFERENCES goldman.entities(id),
    filename              TEXT         NOT NULL,
    mime_type             TEXT,
    source                TEXT         NOT NULL CHECK (source IN ('uploaded', 'email', 'manual')),
    original_storage_path TEXT         NOT NULL,
    summary               TEXT,                                   -- generated once at upload
    uploaded_at           TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_goldman_documents_entity
    ON goldman.documents(entity_id);

CREATE TABLE IF NOT EXISTS goldman.document_chunks (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  UUID         NOT NULL REFERENCES goldman.documents(id) ON DELETE CASCADE,
    chunk_index  INTEGER      NOT NULL,
    text         TEXT         NOT NULL,
    embedding    vector(1536),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_goldman_chunks_document
    ON goldman.document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_goldman_chunks_embedding
    ON goldman.document_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_goldman_chunks_fts
    ON goldman.document_chunks USING gin (to_tsvector('english', text));

COMMENT ON TABLE goldman.documents IS
    'Document metadata. Original file lives in Supabase Storage at original_storage_path.';
```

- [ ] **Step 2: Verify + Commit**

```bash
python3 -c "
from pathlib import Path
sql = Path('migrations/0011_documents.sql').read_text()
assert 'CREATE TABLE IF NOT EXISTS goldman.documents' in sql
assert 'CREATE TABLE IF NOT EXISTS goldman.document_chunks' in sql
assert 'ON DELETE CASCADE' in sql
assert 'UNIQUE (document_id, chunk_index)' in sql
print('OK')
" && git add migrations/0011_documents.sql && git commit -m "Add migration 0011: goldman.documents + document_chunks

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Migration 0012 — goldman.capabilities

**Files:**
- Create: `migrations/0012_capabilities.sql`

- [ ] **Step 1: Write the SQL**

Create `migrations/0012_capabilities.sql`:

```sql
-- Goldman capabilities: developer-curated registry of what Goldman CAN DO.
-- Distinct from learned knowledge. Phase 4 Telegram bot + Phase 5 Claude
-- plugin both reference this for capability discovery.

CREATE TABLE IF NOT EXISTS goldman.capabilities (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT         NOT NULL UNIQUE,
    description TEXT         NOT NULL,
    kind        TEXT         NOT NULL CHECK (kind IN ('tool', 'skill', 'jurisdiction', 'api')),
    payload     JSONB        NOT NULL DEFAULT '{}',
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_goldman_capabilities_kind
    ON goldman.capabilities(kind) WHERE is_active = true;

DROP TRIGGER IF EXISTS trg_capabilities_updated_at ON goldman.capabilities;
CREATE TRIGGER trg_capabilities_updated_at
    BEFORE UPDATE ON goldman.capabilities
    FOR EACH ROW EXECUTE FUNCTION goldman.set_updated_at();
```

- [ ] **Step 2: Verify + Commit**

```bash
python3 -c "
from pathlib import Path
sql = Path('migrations/0012_capabilities.sql').read_text()
assert 'CREATE TABLE IF NOT EXISTS goldman.capabilities' in sql
assert 'JSONB' in sql
assert 'name        TEXT         NOT NULL UNIQUE' in sql
print('OK')
" && git add migrations/0012_capabilities.sql && git commit -m "Add migration 0012: goldman.capabilities

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Migration 0013 — hybrid_search RPC

**Files:**
- Create: `migrations/0013_hybrid_search.sql`

RRF (Reciprocal Rank Fusion) merges vector + keyword rankings.
For each result row, `rrf_score = sum(1 / (k + rank))` across rankers.
Common k = 60. We compute over (facts + turns + chunks) for each leg.

- [ ] **Step 1: Write the SQL**

Create `migrations/0013_hybrid_search.sql`:

```sql
-- Goldman hybrid_search: RRF fusion of vector + keyword across all
-- searchable surfaces (facts, conversation_turns, document_chunks).
-- Per spec §6.3.

CREATE OR REPLACE FUNCTION goldman.hybrid_search(
    p_query_embedding vector(1536),
    p_query_text       TEXT,
    p_entity_id        UUID    DEFAULT NULL,
    p_top_n            INTEGER DEFAULT 20,
    p_rrf_k            INTEGER DEFAULT 60
) RETURNS TABLE (
    source_type TEXT,
    source_id   UUID,
    excerpt     TEXT,
    score       FLOAT,
    entity_id   UUID,
    metadata    JSONB
) LANGUAGE sql STABLE AS $$
WITH
-- VECTOR leg: union all sources, rank globally by cosine distance.
vector_pool AS (
    SELECT 'fact'::TEXT AS source_type, f.id AS source_id,
           f.fact AS excerpt, f.entity_id,
           jsonb_build_object('kind', f.kind, 'source', f.source) AS metadata,
           (f.embedding <=> p_query_embedding) AS distance
    FROM goldman.facts_live f
    WHERE f.embedding IS NOT NULL
      AND (p_entity_id IS NULL OR f.entity_id = p_entity_id OR f.entity_id IS NULL)
    UNION ALL
    SELECT 'turn', t.id, t.text, t.entity_id,
           jsonb_build_object('role', t.role, 'session_id', t.session_id,
                              'front_door', t.front_door),
           (t.embedding <=> p_query_embedding)
    FROM goldman.conversation_turns t
    WHERE t.embedding IS NOT NULL
      AND (p_entity_id IS NULL OR t.entity_id = p_entity_id OR t.entity_id IS NULL)
    UNION ALL
    SELECT 'chunk', c.id, c.text, d.entity_id,
           jsonb_build_object('document_id', d.id, 'filename', d.filename,
                              'chunk_index', c.chunk_index),
           (c.embedding <=> p_query_embedding)
    FROM goldman.document_chunks c
    JOIN goldman.documents d ON d.id = c.document_id
    WHERE c.embedding IS NOT NULL
      AND (p_entity_id IS NULL OR d.entity_id = p_entity_id OR d.entity_id IS NULL)
),
vector_ranked AS (
    SELECT source_type, source_id, excerpt, entity_id, metadata,
           ROW_NUMBER() OVER (ORDER BY distance) AS rk
    FROM vector_pool
    ORDER BY distance
    LIMIT p_top_n * 3
),
-- KEYWORD leg: full-text search, same shape.
keyword_pool AS (
    SELECT 'fact'::TEXT AS source_type, f.id AS source_id,
           f.fact AS excerpt, f.entity_id,
           jsonb_build_object('kind', f.kind, 'source', f.source) AS metadata,
           ts_rank_cd(to_tsvector('english', f.fact),
                      plainto_tsquery('english', p_query_text)) AS rank_score
    FROM goldman.facts_live f
    WHERE to_tsvector('english', f.fact) @@ plainto_tsquery('english', p_query_text)
      AND (p_entity_id IS NULL OR f.entity_id = p_entity_id OR f.entity_id IS NULL)
    UNION ALL
    SELECT 'turn', t.id, t.text, t.entity_id,
           jsonb_build_object('role', t.role, 'session_id', t.session_id,
                              'front_door', t.front_door),
           ts_rank_cd(to_tsvector('english', t.text),
                      plainto_tsquery('english', p_query_text))
    FROM goldman.conversation_turns t
    WHERE to_tsvector('english', t.text) @@ plainto_tsquery('english', p_query_text)
      AND (p_entity_id IS NULL OR t.entity_id = p_entity_id OR t.entity_id IS NULL)
    UNION ALL
    SELECT 'chunk', c.id, c.text, d.entity_id,
           jsonb_build_object('document_id', d.id, 'filename', d.filename,
                              'chunk_index', c.chunk_index),
           ts_rank_cd(to_tsvector('english', c.text),
                      plainto_tsquery('english', p_query_text))
    FROM goldman.document_chunks c
    JOIN goldman.documents d ON d.id = c.document_id
    WHERE to_tsvector('english', c.text) @@ plainto_tsquery('english', p_query_text)
      AND (p_entity_id IS NULL OR d.entity_id = p_entity_id OR d.entity_id IS NULL)
),
keyword_ranked AS (
    SELECT source_type, source_id, excerpt, entity_id, metadata,
           ROW_NUMBER() OVER (ORDER BY rank_score DESC) AS rk
    FROM keyword_pool
    ORDER BY rank_score DESC
    LIMIT p_top_n * 3
),
-- RRF fusion: each row's score is sum over rankers of 1/(k + rank).
-- Within a single (source_type, source_id) all rows have identical
-- excerpt/entity_id/metadata, so MAX() / array_agg()[1] are safe picks.
combined AS (
    SELECT source_type, source_id,
           MAX(excerpt) AS excerpt,
           MAX(entity_id) AS entity_id,
           (array_agg(metadata))[1] AS metadata,
           SUM(1.0 / (p_rrf_k + rk))::FLOAT AS total_score
    FROM (
        SELECT source_type, source_id, excerpt, entity_id, metadata, rk
        FROM vector_ranked
        UNION ALL
        SELECT source_type, source_id, excerpt, entity_id, metadata, rk
        FROM keyword_ranked
    ) u
    GROUP BY source_type, source_id
)
SELECT source_type, source_id, excerpt, total_score AS score,
       entity_id, metadata
FROM combined
ORDER BY total_score DESC
LIMIT p_top_n;
$$;

-- goldman_app_login inherits goldman_app; both can call this function.
GRANT EXECUTE ON FUNCTION goldman.hybrid_search(vector, TEXT, UUID, INTEGER, INTEGER) TO goldman_app;
```

- [ ] **Step 2: Verify + Commit**

```bash
python3 -c "
from pathlib import Path
sql = Path('migrations/0013_hybrid_search.sql').read_text()
assert 'CREATE OR REPLACE FUNCTION goldman.hybrid_search' in sql
assert 'vector_pool' in sql
assert 'keyword_pool' in sql
assert 'RRF' in sql.upper() or '1.0 / (p_rrf_k + rk)' in sql
print('OK')
" && git add migrations/0013_hybrid_search.sql && git commit -m "Add migration 0013: goldman.hybrid_search RPC (vector + keyword + RRF)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Migration 0014 — Supabase Storage bucket

**Files:**
- Create: `migrations/0014_storage_bucket.sql`

Goldman uploads via service-role HTTP (bypasses RLS). The bucket just needs to exist and be private.

- [ ] **Step 1: Write the SQL**

Create `migrations/0014_storage_bucket.sql`:

```sql
-- Register the goldman-documents Storage bucket. Service-role uploads only;
-- RLS not configured because the Goldman service runs with service_role key.

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'goldman-documents',
    'goldman-documents',
    false,
    52428800,                                  -- 50 MB
    ARRAY['application/pdf', 'text/plain', 'text/markdown',
          'application/octet-stream', 'image/png', 'image/jpeg']
) ON CONFLICT (id) DO NOTHING;

-- Reserved for Phase 3 vendor-bill intake.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'goldman-bills',
    'goldman-bills',
    false,
    20971520,                                  -- 20 MB
    ARRAY['application/pdf', 'image/png', 'image/jpeg',
          'text/html', 'application/octet-stream']
) ON CONFLICT (id) DO NOTHING;
```

- [ ] **Step 2: Verify + Commit**

```bash
python3 -c "
from pathlib import Path
sql = Path('migrations/0014_storage_bucket.sql').read_text()
assert 'goldman-documents' in sql
assert 'goldman-bills' in sql
assert 'ON CONFLICT' in sql
print('OK')
" && git add migrations/0014_storage_bucket.sql && git commit -m "Add migration 0014: register goldman-documents + goldman-bills Storage buckets

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Migration 0015 — seed capabilities

**Files:**
- Create: `migrations/0015_seed_capabilities.sql`

- [ ] **Step 1: Write the SQL**

Create `migrations/0015_seed_capabilities.sql`:

```sql
-- Seed initial capabilities (Phase 0/1/2).
-- Idempotent via UNIQUE (name).

INSERT INTO goldman.capabilities (name, description, kind, payload) VALUES
    ('create_invoice', 'Create a client invoice in the right Zoho org for the given entity.',
     'tool', '{"phase": 0, "module": "goldman.zoho", "entry": "invoice_service_for"}'),
    ('list_invoices', 'List recent invoices for an entity, optionally filtered by status.',
     'tool', '{"phase": 0, "cli": "list --entity SLUG"}'),
    ('list_customers', 'List Zoho customers (contacts) for an entity.',
     'tool', '{"phase": 0, "cli": "customers --entity SLUG"}'),
    ('onboard_entity', 'Conversational onboarding: brain-dump → Claude extraction → 5-table writes → coverage check → gap-fill.',
     'skill', '{"phase": 1, "cli": "onboard --entity SLUG", "needs": ["ANTHROPIC_API_KEY"]}'),
    ('sync_zoho_contacts', 'Pull Zoho contacts for an entity into goldman.clients + goldman.vendors.',
     'tool', '{"phase": 1, "cli": "sync zoho-contacts --entity SLUG"}'),
    ('who', 'Print the company brain: each entity with registrations, banks, top clients/vendors.',
     'tool', '{"phase": 1, "cli": "who"}'),
    ('remember_fact', 'Record a free-floating fact for an entity (kind ∈ target/preference/constraint/commitment/event/decision/note).',
     'tool', '{"phase": 2, "cli": "remember --entity SLUG --kind KIND TEXT"}'),
    ('recall', 'Hybrid retrieval (vector + keyword) across facts + conversation turns + document chunks.',
     'tool', '{"phase": 2, "cli": "recall QUESTION [--entity SLUG]", "needs": ["OPENAI_API_KEY"]}'),
    ('document_upload', 'Upload a document (txt/md/pdf), summarise via Claude, chunk + embed.',
     'tool', '{"phase": 2, "cli": "document upload --entity SLUG FILE", "needs": ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOLDMAN_SUPABASE_SERVICE_KEY"]}'),
    ('document_list', 'List documents for an entity.',
     'tool', '{"phase": 2, "cli": "document list [--entity SLUG]"}'),
    ('embed_pending', 'Embed all rows missing embeddings (facts + conversation_turns + document_chunks).',
     'tool', '{"phase": 2, "cli": "db embed-pending", "needs": ["OPENAI_API_KEY"]}'),
    ('jurisdiction_hk', 'Knowledge of Hong Kong profits tax + general HK company-law obligations.',
     'jurisdiction', '{"phase": 2, "primary_taxes": ["profits_tax"]}'),
    ('jurisdiction_us', 'Knowledge of US federal income tax + state sales tax nexus basics.',
     'jurisdiction', '{"phase": 2, "primary_taxes": ["income_tax", "sales_tax"]}')
ON CONFLICT (name) DO NOTHING;
```

- [ ] **Step 2: Verify + Commit**

```bash
python3 -c "
from pathlib import Path
sql = Path('migrations/0015_seed_capabilities.sql').read_text()
assert 'remember_fact' in sql
assert 'recall' in sql
assert 'document_upload' in sql
assert 'ON CONFLICT (name) DO NOTHING' in sql
print('OK')
" && git add migrations/0015_seed_capabilities.sql && git commit -m "Add migration 0015: seed initial Goldman capabilities (Phase 0-2)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: Apply migrations 0009-0015 to live Supabase

**Files:** (no code changes; verification)

- [ ] **Step 1: Run migrator**

```bash
cd ~/Desktop/Obsidian/Projects/zoho-invoice-agent
python3 cli.py db migrate
```

Expected output: `Applied 7 migration(s):` with all 7 listed.

- [ ] **Step 2: Verify schema**

```bash
python3 -c "
import os, psycopg
from dotenv import load_dotenv
load_dotenv()
url = os.environ['GOLDMAN_DB_ADMIN_URL']
with psycopg.connect(url) as conn, conn.cursor() as cur:
    cur.execute(\"\"\"
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'goldman' ORDER BY table_name
    \"\"\")
    print('=== goldman.* tables/views ===')
    for r in cur.fetchall(): print(' ', r[0])
    cur.execute(\"\"\"
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'goldman' AND table_name = 'facts'
        ORDER BY ordinal_position
    \"\"\")
    print('=== goldman.facts columns ===')
    for r in cur.fetchall(): print(' ', r[0])
    cur.execute('SELECT count(*) FROM goldman.capabilities')
    print('=== goldman.capabilities count ===', cur.fetchone()[0])
"
```

Expected: new tables `conversation_turns`, `documents`, `document_chunks`, `capabilities` listed; facts has `embedding` and `conflict_with` columns; capabilities count ≥ 13.

- [ ] **Step 3: Verify goldman_app_login can call hybrid_search**

```bash
python3 -c "
import os, psycopg
from dotenv import load_dotenv
load_dotenv()
url = os.environ['GOLDMAN_DB_APP_URL']
with psycopg.connect(url) as conn, conn.cursor() as cur:
    cur.execute('''
        SELECT * FROM goldman.hybrid_search(
            (SELECT array_agg(0)::vector FROM generate_series(1,1536))::vector(1536),
            'test query', NULL, 5
        )
    ''')
    print('goldman_app_login can call hybrid_search; rows:', len(cur.fetchall()))
"
```

Expected: `rows: 0` (no data yet — but the function executes successfully).

---

## Task 10: ConversationTurnRepository (TDD)

**Files:**
- Create: `goldman_db/conversation_turns.py`
- Test: `tests/test_goldman_conversation_turns_repo.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_conversation_turns_repo.py`:

```python
"""Tests for ConversationTurnRepository."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.conversation_turns import (
    ConversationTurn, ConversationTurnRepository,
)


def test_insert_returns_new_id():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = ConversationTurnRepository(conn)
    eid = uuid4()
    returned = repo.insert(
        entity_id=eid,
        session_id="session_abc",
        front_door="cli",
        role="user",
        text="invoice Acme $500",
    )

    assert returned == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.conversation_turns" in sql


def test_list_by_session_returns_turns_in_order():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    t1 = uuid4(); t2 = uuid4(); eid = uuid4()
    cur.fetchall.return_value = [
        (t1, eid, "s1", "cli", "user", "hello", None),
        (t2, eid, "s1", "cli", "assistant", "hi back", None),
    ]

    repo = ConversationTurnRepository(conn)
    turns = repo.list_by_session("s1")

    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[1].role == "assistant"
    sql = str(cur.execute.call_args)
    assert "ORDER BY created_at" in sql


def test_list_pending_embedding_returns_only_null():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    repo = ConversationTurnRepository(conn)
    repo.list_pending_embedding(limit=10)

    sql = str(cur.execute.call_args)
    assert "embedding IS NULL" in sql
    assert "LIMIT" in sql


def test_set_embedding_writes_vector_string():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = ConversationTurnRepository(conn)
    tid = uuid4()

    repo.set_embedding(tid, [0.1, 0.2, 0.3])

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.conversation_turns" in sql
    assert "SET embedding" in sql
    params = cur.execute.call_args[0][1]
    # The embedding param is the pgvector text format
    assert "0.1" in params[0] and "0.2" in params[0]
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_conversation_turns_repo.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman_db/conversation_turns.py`:

```python
"""Repository for goldman.conversation_turns (append-only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class ConversationTurn:
    id: UUID
    entity_id: Optional[UUID]
    session_id: str
    front_door: str
    role: str
    text: str
    embedding: Optional[list]


_COLS = "id, entity_id, session_id, front_door, role, text, embedding"


def _row(r) -> ConversationTurn:
    return ConversationTurn(
        id=r[0], entity_id=r[1], session_id=r[2],
        front_door=r[3], role=r[4], text=r[5], embedding=r[6],
    )


def _vec_to_str(v) -> str:
    """Serialise a float list to pgvector text format ('[0.1,0.2,...]')."""
    return "[" + ",".join(str(x) for x in v) + "]"


class ConversationTurnRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def insert(
        self,
        *,
        entity_id: Optional[UUID],
        session_id: str,
        front_door: str,
        role: str,
        text: str,
    ) -> UUID:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.conversation_turns
                    (entity_id, session_id, front_door, role, text)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (entity_id, session_id, front_door, role, text),
            )
            return cur.fetchone()[0]

    def list_by_session(self, session_id: str) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.conversation_turns "
                f"WHERE session_id = %s ORDER BY created_at",
                (session_id,),
            )
            return [_row(r) for r in cur.fetchall()]

    def list_pending_embedding(self, *, limit: int = 50) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.conversation_turns "
                f"WHERE embedding IS NULL ORDER BY created_at LIMIT %s",
                (limit,),
            )
            return [_row(r) for r in cur.fetchall()]

    def set_embedding(self, turn_id: UUID, embedding: list) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE goldman.conversation_turns SET embedding = %s::vector WHERE id = %s",
                (_vec_to_str(embedding), turn_id),
            )
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_conversation_turns_repo.py -v 2>&1 | tail -8 && \
git add goldman_db/conversation_turns.py tests/test_goldman_conversation_turns_repo.py && \
git commit -m "Add ConversationTurnRepository (insert + list_by_session + embed pipeline)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 4 tests pass.

---

## Task 11: Document + DocumentChunk Repositories (TDD)

**Files:**
- Create: `goldman_db/documents.py`
- Test: `tests/test_goldman_documents_repo.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_documents_repo.py`:

```python
"""Tests for DocumentRepository + DocumentChunkRepository."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.documents import (
    Document, DocumentChunk,
    DocumentRepository, DocumentChunkRepository,
)


def test_document_insert_returns_id():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = DocumentRepository(conn)
    eid = uuid4()
    returned = repo.insert(
        entity_id=eid,
        filename="UK_VAT_Strategy_v2.pdf",
        mime_type="application/pdf",
        source="uploaded",
        original_storage_path="documents/amzg/2026/abc-uk_vat.pdf",
    )

    assert returned == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.documents" in sql


def test_document_set_summary_updates_row():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = DocumentRepository(conn)
    did = uuid4()

    repo.set_summary(did, "Two-page advisor letter on UK VAT.")

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.documents" in sql
    assert "summary" in sql


def test_chunk_insert_returns_id():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = DocumentChunkRepository(conn)
    did = uuid4()

    returned = repo.insert(
        document_id=did,
        chunk_index=0,
        text="The advisor flagged the Texas economic-nexus threshold at $500k.",
    )

    assert returned == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.document_chunks" in sql


def test_chunk_list_pending_embedding():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    repo = DocumentChunkRepository(conn)
    repo.list_pending_embedding(limit=20)

    sql = str(cur.execute.call_args)
    assert "embedding IS NULL" in sql


def test_chunk_set_embedding():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = DocumentChunkRepository(conn)
    cid = uuid4()

    repo.set_embedding(cid, [0.1] * 3)

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.document_chunks SET embedding" in sql


def test_document_list_by_entity():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    did = uuid4(); eid = uuid4()
    cur.fetchall.return_value = [
        (did, eid, "letter.pdf", "application/pdf", "uploaded",
         "documents/amzg/2026/letter.pdf", "Summary text", None),
    ]

    repo = DocumentRepository(conn)
    docs = repo.list_by_entity(eid)

    assert len(docs) == 1
    assert docs[0].filename == "letter.pdf"
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_documents_repo.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman_db/documents.py`:

```python
"""Repositories for goldman.documents + goldman.document_chunks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class Document:
    id: UUID
    entity_id: Optional[UUID]
    filename: str
    mime_type: Optional[str]
    source: str
    original_storage_path: str
    summary: Optional[str]
    uploaded_at: Optional[object]


@dataclass(frozen=True)
class DocumentChunk:
    id: UUID
    document_id: UUID
    chunk_index: int
    text: str
    embedding: Optional[list]


_DOC_COLS = """
    id, entity_id, filename, mime_type, source,
    original_storage_path, summary, uploaded_at
"""
_CHUNK_COLS = "id, document_id, chunk_index, text, embedding"


def _vec_to_str(v) -> str:
    return "[" + ",".join(str(x) for x in v) + "]"


def _doc(r) -> Document:
    return Document(
        id=r[0], entity_id=r[1], filename=r[2], mime_type=r[3],
        source=r[4], original_storage_path=r[5],
        summary=r[6], uploaded_at=r[7] if len(r) > 7 else None,
    )


def _chunk(r) -> DocumentChunk:
    return DocumentChunk(
        id=r[0], document_id=r[1], chunk_index=r[2],
        text=r[3], embedding=r[4] if len(r) > 4 else None,
    )


class DocumentRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def insert(
        self,
        *,
        entity_id: Optional[UUID],
        filename: str,
        mime_type: Optional[str],
        source: str,
        original_storage_path: str,
    ) -> UUID:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.documents
                    (entity_id, filename, mime_type, source, original_storage_path)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (entity_id, filename, mime_type, source, original_storage_path),
            )
            return cur.fetchone()[0]

    def set_summary(self, document_id: UUID, summary: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE goldman.documents SET summary = %s WHERE id = %s",
                (summary, document_id),
            )

    def list_by_entity(self, entity_id: UUID) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_DOC_COLS} FROM goldman.documents "
                f"WHERE entity_id = %s ORDER BY uploaded_at DESC",
                (entity_id,),
            )
            return [_doc(r) for r in cur.fetchall()]

    def list_all(self) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_DOC_COLS} FROM goldman.documents "
                f"ORDER BY uploaded_at DESC"
            )
            return [_doc(r) for r in cur.fetchall()]

    def get(self, document_id: UUID) -> Optional[Document]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_DOC_COLS} FROM goldman.documents WHERE id = %s",
                (document_id,),
            )
            row = cur.fetchone()
            return _doc(row) if row else None


class DocumentChunkRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def insert(
        self,
        *,
        document_id: UUID,
        chunk_index: int,
        text: str,
    ) -> UUID:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.document_chunks
                    (document_id, chunk_index, text)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (document_id, chunk_index, text),
            )
            return cur.fetchone()[0]

    def list_pending_embedding(self, *, limit: int = 50) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_CHUNK_COLS} FROM goldman.document_chunks "
                f"WHERE embedding IS NULL ORDER BY created_at LIMIT %s",
                (limit,),
            )
            return [_chunk(r) for r in cur.fetchall()]

    def set_embedding(self, chunk_id: UUID, embedding: list) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE goldman.document_chunks SET embedding = %s::vector WHERE id = %s",
                (_vec_to_str(embedding), chunk_id),
            )

    def list_by_document(self, document_id: UUID) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_CHUNK_COLS} FROM goldman.document_chunks "
                f"WHERE document_id = %s ORDER BY chunk_index",
                (document_id,),
            )
            return [_chunk(r) for r in cur.fetchall()]
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_documents_repo.py -v 2>&1 | tail -10 && \
git add goldman_db/documents.py tests/test_goldman_documents_repo.py && \
git commit -m "Add DocumentRepository + DocumentChunkRepository

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 6 tests pass.

---

## Task 12: CapabilityRepository (TDD)

**Files:**
- Create: `goldman_db/capabilities.py`
- Test: `tests/test_goldman_capabilities_repo.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_capabilities_repo.py`:

```python
"""Tests for CapabilityRepository."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.capabilities import Capability, CapabilityRepository


def test_list_active_filters_by_is_active():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cap_id = uuid4()
    cur.fetchall.return_value = [
        (cap_id, "recall", "Hybrid retrieval.",
         "tool", {"phase": 2}, True),
    ]

    repo = CapabilityRepository(conn)
    caps = repo.list_active()

    assert len(caps) == 1
    assert caps[0].name == "recall"
    sql = str(cur.execute.call_args)
    assert "is_active = true" in sql.lower() or "is_active = TRUE" in sql


def test_get_by_name_returns_capability():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cap_id = uuid4()
    cur.fetchone.return_value = (cap_id, "recall", "Hybrid retrieval.",
                                  "tool", {"phase": 2}, True)

    repo = CapabilityRepository(conn)
    cap = repo.get_by_name("recall")

    assert cap is not None
    assert cap.kind == "tool"


def test_list_by_kind():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    repo = CapabilityRepository(conn)
    repo.list_by_kind("jurisdiction")

    sql = str(cur.execute.call_args)
    assert "kind = %s" in sql
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_capabilities_repo.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman_db/capabilities.py`:

```python
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
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_capabilities_repo.py -v 2>&1 | tail -6 && \
git add goldman_db/capabilities.py tests/test_goldman_capabilities_repo.py && \
git commit -m "Add CapabilityRepository (list_active/list_by_kind/get_by_name)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 3 tests pass.

---

## Task 13: Extend FactRepository (embedding + conflict)

**Files:**
- Modify: `goldman_db/facts.py`
- Modify: `tests/test_goldman_facts_repo.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_goldman_facts_repo.py`:

```python
def test_list_pending_embedding():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    repo = FactRepository(conn)
    repo.list_pending_embedding(limit=10)

    sql = str(cur.execute.call_args)
    assert "embedding IS NULL" in sql
    assert "LIMIT" in sql


def test_set_embedding():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = FactRepository(conn)
    fid = uuid4()

    repo.set_embedding(fid, [0.1, 0.2, 0.3])

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.facts SET embedding" in sql


def test_find_potential_conflicts_uses_cosine_threshold():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    repo = FactRepository(conn)
    fid = uuid4()

    repo.find_potential_conflicts(fid, similarity_threshold=0.85)

    sql = str(cur.execute.call_args)
    # uses cosine similarity threshold
    assert "<=>" in sql
    assert "0.15" in sql or "0.85" in sql  # threshold somewhere


def test_mark_conflict_writes_array_on_both_rows():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = FactRepository(conn)
    a = uuid4(); b = uuid4()

    repo.mark_conflict(a, b)

    # Two UPDATEs — one per row
    assert cur.execute.call_count == 2
    sqls = [str(c) for c in cur.execute.call_args_list]
    assert any("conflict_with" in s for s in sqls)
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_facts_repo.py -v 2>&1 | tail -8
```

Expected: 4 new tests fail with AttributeError.

- [ ] **Step 3: Extend `goldman_db/facts.py`**

Append these methods to the `FactRepository` class (after `list_live_by_entity`):

```python
    def list_pending_embedding(self, *, limit: int = 50) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.facts "
                f"WHERE embedding IS NULL ORDER BY created_at LIMIT %s",
                (limit,),
            )
            return [_row(r) for r in cur.fetchall()]

    def set_embedding(self, fact_id, embedding: list) -> None:
        vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE goldman.facts SET embedding = %s::vector WHERE id = %s",
                (vec_str, fact_id),
            )

    def find_potential_conflicts(
        self, fact_id, *, similarity_threshold: float = 0.85, limit: int = 5,
    ) -> list:
        """Return facts whose embeddings are very close to this fact's but
        whose content_hash differs (suggesting contradictory statements about
        the same topic). Caller decides whether to mark_conflict.
        """
        distance_threshold = 1.0 - similarity_threshold
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS} FROM goldman.facts other
                WHERE other.embedding IS NOT NULL
                  AND other.id != %s
                  AND other.content_hash != (
                      SELECT content_hash FROM goldman.facts WHERE id = %s
                  )
                  AND (
                      other.embedding <=> (
                          SELECT embedding FROM goldman.facts WHERE id = %s
                      )
                  ) < {distance_threshold:.3f}
                ORDER BY other.embedding <=> (
                    SELECT embedding FROM goldman.facts WHERE id = %s
                )
                LIMIT %s
                """,
                (fact_id, fact_id, fact_id, fact_id, limit),
            )
            return [_row(r) for r in cur.fetchall()]

    def mark_conflict(self, fact_a, fact_b) -> None:
        """Add each fact's id to the other's conflict_with array. Idempotent."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.facts
                SET conflict_with = ARRAY(SELECT DISTINCT unnest(conflict_with || %s::uuid))
                WHERE id = %s
                """,
                (fact_b, fact_a),
            )
            cur.execute(
                """
                UPDATE goldman.facts
                SET conflict_with = ARRAY(SELECT DISTINCT unnest(conflict_with || %s::uuid))
                WHERE id = %s
                """,
                (fact_a, fact_b),
            )
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_facts_repo.py -v 2>&1 | tail -10 && \
git add goldman_db/facts.py tests/test_goldman_facts_repo.py && \
git commit -m "FactRepository: add embed-pending + conflict surface

Methods: list_pending_embedding (for embed worker), set_embedding,
find_potential_conflicts (cosine threshold), mark_conflict (mutual).
Auto-detection of conflicts is Phase 6.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 7 tests pass (3 original + 4 new).

---

## Task 14: EmbeddingClient (OpenAI wrapper, TDD)

**Files:**
- Create: `goldman/embeddings.py`
- Test: `tests/test_goldman_embeddings.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_embeddings.py`:

```python
"""Tests for EmbeddingClient + embed_pending_in."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from goldman.embeddings import (
    EmbeddingClient, EmbeddingConfigError, embed_pending_in,
)


def test_client_raises_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(EmbeddingConfigError):
        EmbeddingClient()


def test_embed_batch_returns_vectors_in_order(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    with patch("goldman.embeddings.openai.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        # Three rows; each has .embedding
        mock_resp.data = [
            MagicMock(embedding=[0.1, 0.2]),
            MagicMock(embedding=[0.3, 0.4]),
            MagicMock(embedding=[0.5, 0.6]),
        ]
        mock_client.embeddings.create.return_value = mock_resp
        mock_openai.return_value = mock_client

        client = EmbeddingClient()
        vectors = client.embed_batch(["a", "b", "c"])

        assert vectors == [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
        kwargs = mock_client.embeddings.create.call_args.kwargs
        assert kwargs["model"] == "text-embedding-3-small"


def test_embed_pending_in_processes_facts_turns_chunks(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    fake_facts = MagicMock()
    fake_facts.list_pending_embedding.return_value = [
        MagicMock(id=uuid4(), fact="UK VAT registered"),
    ]
    fake_turns = MagicMock()
    fake_turns.list_pending_embedding.return_value = []
    fake_chunks = MagicMock()
    fake_chunks.list_pending_embedding.return_value = []

    fake_embedder = MagicMock()
    fake_embedder.embed_batch.return_value = [[0.1] * 1536]

    summary = embed_pending_in(
        facts_repo=fake_facts,
        turns_repo=fake_turns,
        chunks_repo=fake_chunks,
        embedder=fake_embedder,
        batch_size=10,
    )

    fake_facts.set_embedding.assert_called_once()
    assert summary["facts"] == 1
    assert summary["turns"] == 0
    assert summary["chunks"] == 0
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_embeddings.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman/embeddings.py`:

```python
"""OpenAI embedding client + batch worker for goldman pending rows."""

from __future__ import annotations

import os
from typing import Optional

import openai


DEFAULT_MODEL = "text-embedding-3-small"


class EmbeddingConfigError(RuntimeError):
    """Raised when the OpenAI API key is missing."""


class EmbeddingClient:
    def __init__(self, *, model: str = DEFAULT_MODEL):
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise EmbeddingConfigError(
                "OPENAI_API_KEY not set. Goldman embeddings need it."
            )
        self._client = openai.OpenAI(api_key=api_key)
        self.model = model

    def embed_batch(self, texts: list) -> list:
        if not texts:
            return []
        # OpenAI input limit per request is ~8191 tokens per text; batch
        # size in count is fine up to ~2048. Caller handles bigger batches.
        resp = self._client.embeddings.create(
            model=self.model,
            input=texts,
            encoding_format="float",
        )
        return [list(d.embedding) for d in resp.data]


def embed_pending_in(
    *,
    facts_repo,
    turns_repo,
    chunks_repo,
    embedder: EmbeddingClient,
    batch_size: int = 50,
) -> dict:
    """Embed all rows with NULL embeddings across facts, turns, chunks.

    Returns a summary dict {facts: N, turns: N, chunks: N}.
    """
    summary = {"facts": 0, "turns": 0, "chunks": 0}

    # FACTS
    facts = facts_repo.list_pending_embedding(limit=batch_size)
    while facts:
        texts = [f.fact for f in facts]
        vectors = embedder.embed_batch(texts)
        for f, v in zip(facts, vectors):
            facts_repo.set_embedding(f.id, v)
            summary["facts"] += 1
        facts = facts_repo.list_pending_embedding(limit=batch_size)

    # TURNS
    turns = turns_repo.list_pending_embedding(limit=batch_size)
    while turns:
        texts = [t.text for t in turns]
        vectors = embedder.embed_batch(texts)
        for t, v in zip(turns, vectors):
            turns_repo.set_embedding(t.id, v)
            summary["turns"] += 1
        turns = turns_repo.list_pending_embedding(limit=batch_size)

    # CHUNKS
    chunks = chunks_repo.list_pending_embedding(limit=batch_size)
    while chunks:
        texts = [c.text for c in chunks]
        vectors = embedder.embed_batch(texts)
        for c, v in zip(chunks, vectors):
            chunks_repo.set_embedding(c.id, v)
            summary["chunks"] += 1
        chunks = chunks_repo.list_pending_embedding(limit=batch_size)

    return summary
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_embeddings.py -v 2>&1 | tail -6 && \
git add goldman/embeddings.py tests/test_goldman_embeddings.py && \
git commit -m "Add EmbeddingClient (OpenAI text-embedding-3-small) + embed_pending_in batch worker

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 3 tests pass.

---

## Task 15: Chunker (tiktoken, TDD)

**Files:**
- Create: `goldman/chunker.py`
- Test: `tests/test_goldman_chunker.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_chunker.py`:

```python
"""Tests for chunk_text."""

from __future__ import annotations

from goldman.chunker import chunk_text


def test_short_text_returns_one_chunk():
    chunks = chunk_text("hello world", max_tokens=512, overlap_tokens=64)
    assert chunks == ["hello world"]


def test_long_text_splits_with_overlap():
    # Build a string of ~1600 tokens (~6400 chars at 4 chars/token).
    text = ("the cat sat on the mat " * 1500).strip()
    chunks = chunk_text(text, max_tokens=512, overlap_tokens=64)
    # Should produce multiple chunks.
    assert len(chunks) >= 3
    # Each chunk is non-empty.
    assert all(c.strip() for c in chunks)


def test_overlap_creates_shared_prefix_suffix():
    text = " ".join(f"word{i}" for i in range(2000))
    chunks = chunk_text(text, max_tokens=200, overlap_tokens=20)
    # The end of one chunk should appear at the start of the next.
    if len(chunks) >= 2:
        tail = chunks[0].split()[-5:]
        head = chunks[1].split()[:30]
        # at least one of the tail words should appear in the head
        assert any(w in head for w in tail)
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_chunker.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman/chunker.py`:

```python
"""Token-aware text chunking using tiktoken (cl100k_base).

Returns chunks of <= max_tokens with overlap_tokens of overlap between
adjacent chunks. Whitespace is preserved; chunks may break mid-sentence.
"""

from __future__ import annotations

import tiktoken


_ENC = tiktoken.get_encoding("cl100k_base")


def chunk_text(
    text: str, *, max_tokens: int = 512, overlap_tokens: int = 64,
) -> list:
    if not text:
        return []

    tokens = _ENC.encode(text)
    if len(tokens) <= max_tokens:
        return [text]

    step = max_tokens - overlap_tokens
    if step <= 0:
        raise ValueError("overlap_tokens must be < max_tokens")

    chunks: list = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        slice_tokens = tokens[start:end]
        chunks.append(_ENC.decode(slice_tokens))
        if end == len(tokens):
            break
        start += step
    return chunks
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_chunker.py -v 2>&1 | tail -6 && \
git add goldman/chunker.py tests/test_goldman_chunker.py && \
git commit -m "Add chunk_text (tiktoken cl100k_base, 512-token windows, 64-token overlap)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 3 tests pass.

---

## Task 16: SupabaseStorage client (TDD)

**Files:**
- Create: `goldman/storage.py`
- Test: `tests/test_goldman_storage.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_storage.py`:

```python
"""Tests for SupabaseStorage."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from goldman.storage import SupabaseStorage, StorageConfigError


def test_raises_when_env_missing(monkeypatch):
    monkeypatch.delenv("GOLDMAN_SUPABASE_URL", raising=False)
    monkeypatch.delenv("GOLDMAN_SUPABASE_SERVICE_KEY", raising=False)

    with pytest.raises(StorageConfigError):
        SupabaseStorage()


def test_upload_sends_put_with_service_key(monkeypatch):
    monkeypatch.setenv("GOLDMAN_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("GOLDMAN_SUPABASE_SERVICE_KEY", "sk_test")

    with patch("goldman.storage.requests.put") as mock_put:
        mock_put.return_value.status_code = 200
        mock_put.return_value.raise_for_status = MagicMock()

        s = SupabaseStorage()
        s.upload(
            bucket="goldman-documents",
            path="amzg/2026/foo.pdf",
            content=b"%PDF...",
            content_type="application/pdf",
        )

        args, kwargs = mock_put.call_args
        assert "goldman-documents/amzg/2026/foo.pdf" in args[0]
        assert kwargs["headers"]["Authorization"] == "Bearer sk_test"
        assert kwargs["headers"]["Content-Type"] == "application/pdf"
        assert kwargs["data"] == b"%PDF..."


def test_download_returns_response_body(monkeypatch):
    monkeypatch.setenv("GOLDMAN_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("GOLDMAN_SUPABASE_SERVICE_KEY", "sk_test")

    with patch("goldman.storage.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.content = b"file bytes"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        s = SupabaseStorage()
        body = s.download(bucket="goldman-documents", path="amzg/x.pdf")

        assert body == b"file bytes"
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_storage.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman/storage.py`:

```python
"""Supabase Storage HTTP client (service-role; bypasses RLS).

Used only by Goldman code. Reads GOLDMAN_SUPABASE_URL and
GOLDMAN_SUPABASE_SERVICE_KEY from env.
"""

from __future__ import annotations

import os

import requests


class StorageConfigError(RuntimeError):
    pass


class SupabaseStorage:
    def __init__(self):
        url = os.getenv("GOLDMAN_SUPABASE_URL", "")
        key = os.getenv("GOLDMAN_SUPABASE_SERVICE_KEY", "")
        if not url or not key:
            raise StorageConfigError(
                "GOLDMAN_SUPABASE_URL and GOLDMAN_SUPABASE_SERVICE_KEY required."
            )
        self.base_url = url.rstrip("/")
        self.service_key = key

    def _url(self, bucket: str, path: str) -> str:
        path = path.lstrip("/")
        return f"{self.base_url}/storage/v1/object/{bucket}/{path}"

    def upload(self, *, bucket: str, path: str, content: bytes, content_type: str) -> None:
        url = self._url(bucket, path)
        resp = requests.put(
            url,
            data=content,
            headers={
                "Authorization": f"Bearer {self.service_key}",
                "Content-Type": content_type,
                "x-upsert": "true",
            },
            timeout=60,
        )
        resp.raise_for_status()

    def download(self, *, bucket: str, path: str) -> bytes:
        url = self._url(bucket, path)
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {self.service_key}"},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.content
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_storage.py -v 2>&1 | tail -6 && \
git add goldman/storage.py tests/test_goldman_storage.py && \
git commit -m "Add SupabaseStorage (service-role HTTP upload/download)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 3 tests pass.

---

## Task 17: Document upload flow (storage + summarise + chunk + insert)

**Files:**
- Create: `goldman/documents.py`
- Test: `tests/test_goldman_documents_upload.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_documents_upload.py`:

```python
"""Tests for upload_document flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from pathlib import Path
from uuid import uuid4

import pytest

from goldman.documents import upload_document


def test_upload_uploads_writes_doc_and_chunks(monkeypatch, tmp_path):
    # A short text file fits in a single chunk.
    f = tmp_path / "letter.txt"
    f.write_text("This is a short advisor letter.")

    # Fakes
    storage = MagicMock()
    storage.upload = MagicMock()
    doc_repo = MagicMock()
    new_doc_id = uuid4()
    doc_repo.insert.return_value = new_doc_id
    chunk_repo = MagicMock()
    chunk_repo.insert.return_value = uuid4()
    summariser = MagicMock()
    summariser.summarise.return_value = "A short letter."

    eid = uuid4()
    result = upload_document(
        file_path=f,
        entity_id=eid,
        entity_slug="amzg",
        storage=storage,
        doc_repo=doc_repo,
        chunk_repo=chunk_repo,
        summariser=summariser,
        bucket="goldman-documents",
        source="uploaded",
    )

    # Storage upload was called
    storage.upload.assert_called_once()
    bucket = storage.upload.call_args.kwargs["bucket"]
    assert bucket == "goldman-documents"

    # Document row inserted
    doc_repo.insert.assert_called_once()
    insert_kwargs = doc_repo.insert.call_args.kwargs
    assert insert_kwargs["entity_id"] == eid
    assert insert_kwargs["filename"] == "letter.txt"

    # Summary set
    doc_repo.set_summary.assert_called_once_with(new_doc_id, "A short letter.")

    # At least one chunk inserted
    assert chunk_repo.insert.call_count >= 1
    assert result.document_id == new_doc_id
    assert result.chunk_count >= 1


def test_upload_extracts_text_from_pdf(monkeypatch, tmp_path):
    f = tmp_path / "report.pdf"
    f.write_bytes(b"%PDF-1.4\n")    # minimal-ish PDF bytes

    with patch("goldman.documents.extract_text_from_pdf") as mock_extract:
        mock_extract.return_value = "Extracted PDF text."

        storage = MagicMock()
        doc_repo = MagicMock()
        doc_repo.insert.return_value = uuid4()
        chunk_repo = MagicMock()
        chunk_repo.insert.return_value = uuid4()
        summariser = MagicMock()
        summariser.summarise.return_value = "Summary"

        upload_document(
            file_path=f,
            entity_id=uuid4(),
            entity_slug="amzg",
            storage=storage,
            doc_repo=doc_repo,
            chunk_repo=chunk_repo,
            summariser=summariser,
            bucket="goldman-documents",
        )

        mock_extract.assert_called_once()
        # The text used for chunking should be the extracted text.
        chunk_text_arg = chunk_repo.insert.call_args.kwargs["text"]
        assert "Extracted PDF text." in chunk_text_arg
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_documents_upload.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman/documents.py`:

```python
"""Document upload flow: storage upload + Claude summary + chunk + insert."""

from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from goldman.chunker import chunk_text


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(name: str) -> str:
    return _SAFE_NAME.sub("_", name)


def extract_text_from_pdf(file_path: Path) -> str:
    """Pull raw text from a PDF using pypdf."""
    from pypdf import PdfReader
    reader = PdfReader(str(file_path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n\n".join(pages).strip()


def _read_text(file_path: Path, mime_type: str) -> str:
    if mime_type == "application/pdf":
        return extract_text_from_pdf(file_path)
    return file_path.read_text(errors="replace")


@dataclass
class UploadResult:
    document_id: UUID
    chunk_count: int
    storage_path: str


def upload_document(
    *,
    file_path: Path,
    entity_id: UUID,
    entity_slug: str,
    storage,
    doc_repo,
    chunk_repo,
    summariser,
    bucket: str,
    source: str = "uploaded",
    chunk_max_tokens: int = 512,
    chunk_overlap_tokens: int = 64,
) -> UploadResult:
    """Upload one document end-to-end.

    storage      — SupabaseStorage instance
    doc_repo     — DocumentRepository instance
    chunk_repo   — DocumentChunkRepository instance
    summariser   — anything with .summarise(text) -> str
    """
    mime_type, _ = mimetypes.guess_type(file_path.name)
    mime_type = mime_type or "application/octet-stream"

    # 1. Storage upload
    body = file_path.read_bytes()
    year = datetime.utcnow().year
    storage_path = f"{entity_slug}/{year}/{uuid4().hex[:8]}-{_safe_filename(file_path.name)}"
    storage.upload(
        bucket=bucket,
        path=storage_path,
        content=body,
        content_type=mime_type,
    )

    # 2. Insert metadata row
    doc_id = doc_repo.insert(
        entity_id=entity_id,
        filename=file_path.name,
        mime_type=mime_type,
        source=source,
        original_storage_path=storage_path,
    )

    # 3. Extract text and chunk
    text = _read_text(file_path, mime_type)
    chunks = chunk_text(
        text,
        max_tokens=chunk_max_tokens,
        overlap_tokens=chunk_overlap_tokens,
    )

    # 4. Insert chunks
    for idx, chunk in enumerate(chunks):
        chunk_repo.insert(
            document_id=doc_id,
            chunk_index=idx,
            text=chunk,
        )

    # 5. Summarise (one-shot via Claude Haiku)
    if text.strip():
        try:
            summary = summariser.summarise(text)
            doc_repo.set_summary(doc_id, summary)
        except Exception:
            # Non-fatal: chunks are searchable even without a summary.
            pass

    return UploadResult(
        document_id=doc_id,
        chunk_count=len(chunks),
        storage_path=storage_path,
    )
```

Also create a small `DocumentSummariser` in `goldman/llm.py` — open `goldman/llm.py` and append:

```python
SUMMARY_MODEL = "claude-haiku-4-5-20251001"


class DocumentSummariser:
    """One-shot two-sentence summary via Claude Haiku."""

    def __init__(self, *, model: str = SUMMARY_MODEL):
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise LLMConfigError(
                "ANTHROPIC_API_KEY not set. DocumentSummariser needs it."
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def summarise(self, text: str, *, max_chars: int = 12000) -> str:
        clipped = text if len(text) <= max_chars else text[:max_chars]
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    "Summarise this document in 2-3 sentences. Focus on what "
                    "it is and key points. Output the summary only, no preamble.\n\n"
                    + clipped
                ),
            }],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                return block.text.strip()
        return ""
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_documents_upload.py -v 2>&1 | tail -6 && \
git add goldman/documents.py goldman/llm.py tests/test_goldman_documents_upload.py && \
git commit -m "Add upload_document flow + DocumentSummariser (Claude Haiku)

End-to-end: storage upload -> metadata row -> text extract -> chunk -> insert -> summary.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 2 tests pass.

---

## Task 18: hybrid_search Python wrapper (TDD)

**Files:**
- Create: `goldman_db/hybrid_search.py`
- Test: `tests/test_goldman_hybrid_search.py`

Calls the SQL RPC + maps rows into a structured result.

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_hybrid_search.py`:

```python
"""Tests for the hybrid_search Python wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.hybrid_search import HybridSearchResult, hybrid_search


def test_hybrid_search_calls_rpc_with_args():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []
    eid = uuid4()

    hybrid_search(
        conn,
        query_embedding=[0.0] * 1536,
        query_text="UK VAT",
        entity_id=eid,
        top_n=10,
    )

    sql = str(cur.execute.call_args)
    assert "goldman.hybrid_search" in sql
    params = cur.execute.call_args[0][1]
    assert eid in params
    assert 10 in params


def test_hybrid_search_maps_rows_to_results():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    sid = uuid4()
    cur.fetchall.return_value = [
        ("fact", sid, "UK VAT registered GB123",
         0.42, None, {"kind": "decision"}),
    ]

    results = hybrid_search(
        conn, query_embedding=[0.0] * 1536, query_text="vat", top_n=5,
    )

    assert len(results) == 1
    assert isinstance(results[0], HybridSearchResult)
    assert results[0].source_type == "fact"
    assert results[0].excerpt.startswith("UK VAT")
    assert results[0].score == 0.42
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_hybrid_search.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman_db/hybrid_search.py`:

```python
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
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_hybrid_search.py -v 2>&1 | tail -6 && \
git add goldman_db/hybrid_search.py tests/test_goldman_hybrid_search.py && \
git commit -m "Add hybrid_search Python wrapper around the RPC

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 2 tests pass.

---

## Task 19: CLI — `remember`

**Files:**
- Modify: `cli.py`

- [ ] **Step 1: Add the command**

In `cli.py`, after the `onboard` command (before the `db` group), add:

```python
@cli.command("remember")
@click.option("--entity", default="amzg",
              help="Entity slug; 'global' for cross-entity facts")
@click.option("--kind", required=True,
              type=click.Choice(["target", "preference", "constraint",
                                 "commitment", "event", "decision", "note"]),
              help="Fact kind")
@click.argument("text")
def remember_cmd(entity, kind, text):
    """Record a free-floating fact for an entity."""
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository
    from goldman_db.facts import FactRepository

    with app_conn() as conn:
        entity_id = None
        if entity != "global":
            ent = EntityRepository(conn).get_by_slug(entity)
            if not ent:
                raise click.ClickException(f"Unknown entity: {entity}")
            entity_id = ent.id
        facts = FactRepository(conn)
        new_id = facts.upsert(
            entity_id=entity_id,
            kind=kind,
            fact=text,
            source="user_explicit",
        )
    click.echo(f"  ok stored fact {new_id}")
```

- [ ] **Step 2: Verify**

```bash
python3 cli.py remember --help 2>&1 | head -10
```

Expected: shows help with `--kind` required and TEXT argument.

- [ ] **Step 3: Commit**

```bash
git add cli.py
git commit -m "CLI: add 'remember' command (manual fact insertion)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 20: CLI — `recall`

**Files:**
- Modify: `cli.py`

- [ ] **Step 1: Add the command**

In `cli.py`, after `remember_cmd`, add:

```python
@cli.command("recall")
@click.option("--entity", default=None,
              help="Restrict search to this entity (omit = cross-entity)")
@click.option("--top", default=10, type=int)
@click.argument("question")
def recall_cmd(entity, top, question):
    """Hybrid search (vector + keyword) across Goldman's memory.

    Returns top results from facts + conversation turns + document chunks
    with their source pointers.
    """
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository
    from goldman_db.hybrid_search import hybrid_search
    from goldman.embeddings import EmbeddingClient

    embedder = EmbeddingClient()
    query_vec = embedder.embed_batch([question])[0]

    with app_conn() as conn:
        entity_id = None
        if entity:
            ent = EntityRepository(conn).get_by_slug(entity.lower())
            if not ent:
                raise click.ClickException(f"Unknown entity: {entity}")
            entity_id = ent.id

        results = hybrid_search(
            conn,
            query_embedding=query_vec,
            query_text=question,
            entity_id=entity_id,
            top_n=top,
        )

    if not results:
        click.echo("(no results)")
        return

    for i, r in enumerate(results, 1):
        click.echo(f"\n{i}. [{r.source_type}] score={r.score:.3f}")
        click.echo(f"   {r.excerpt[:200]}")
        if r.metadata:
            click.echo(f"   meta: {r.metadata}")
```

- [ ] **Step 2: Verify**

```bash
python3 cli.py recall --help 2>&1 | head -8
```

Expected: shows help with QUESTION argument.

- [ ] **Step 3: Commit**

```bash
git add cli.py
git commit -m "CLI: add 'recall' command (hybrid search over Goldman memory)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 21: CLI — `document upload` + `document list`

**Files:**
- Modify: `cli.py`

- [ ] **Step 1: Add the document group + commands**

In `cli.py`, after the `recall_cmd`, add:

```python
# -----------------------------------------------------------------------------
# Documents
# -----------------------------------------------------------------------------

@cli.group()
def document():
    """Goldman document store."""


@document.command("upload")
@click.option("--entity", required=True, help="Entity slug")
@click.argument("file", type=click.Path(exists=True))
def document_upload(entity, file):
    """Upload a document (txt/md/pdf), summarise via Claude, chunk + insert."""
    from pathlib import Path
    from goldman.documents import upload_document
    from goldman.llm import DocumentSummariser
    from goldman.storage import SupabaseStorage
    from goldman_db.connection import app_conn
    from goldman_db.documents import DocumentChunkRepository, DocumentRepository
    from goldman_db.entities import EntityRepository

    storage = SupabaseStorage()
    summariser = DocumentSummariser()

    with app_conn() as conn:
        ent = EntityRepository(conn).get_by_slug(entity.lower())
        if not ent:
            raise click.ClickException(f"Unknown entity: {entity}")
        doc_repo = DocumentRepository(conn)
        chunk_repo = DocumentChunkRepository(conn)

        result = upload_document(
            file_path=Path(file),
            entity_id=ent.id,
            entity_slug=ent.slug,
            storage=storage,
            doc_repo=doc_repo,
            chunk_repo=chunk_repo,
            summariser=summariser,
            bucket="goldman-documents",
        )

    click.echo(
        f"  ok uploaded {Path(file).name}: "
        f"doc_id={result.document_id}, chunks={result.chunk_count}, "
        f"path={result.storage_path}"
    )
    click.echo("  -> run `db embed-pending` to embed the chunks for retrieval.")


@document.command("list")
@click.option("--entity", default=None)
def document_list(entity):
    """List documents (all entities or one)."""
    from goldman_db.connection import app_conn
    from goldman_db.documents import DocumentRepository
    from goldman_db.entities import EntityRepository

    with app_conn() as conn:
        doc_repo = DocumentRepository(conn)
        if entity:
            ent = EntityRepository(conn).get_by_slug(entity.lower())
            if not ent:
                raise click.ClickException(f"Unknown entity: {entity}")
            docs = doc_repo.list_by_entity(ent.id)
        else:
            docs = doc_repo.list_all()

    if not docs:
        click.echo("(no documents)")
        return

    for d in docs:
        click.echo(f"  {d.filename}")
        click.echo(f"    id:   {d.id}")
        click.echo(f"    path: {d.original_storage_path}")
        if d.summary:
            click.echo(f"    summary: {d.summary[:150]}")
```

- [ ] **Step 2: Verify**

```bash
python3 cli.py document --help && python3 cli.py document upload --help 2>&1 | head -8
```

Expected: both helps render.

- [ ] **Step 3: Commit**

```bash
git add cli.py
git commit -m "CLI: add 'document upload' + 'document list' commands

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 22: CLI — `db embed-pending`

**Files:**
- Modify: `cli.py`

- [ ] **Step 1: Add the command inside the `db` group**

In `cli.py`, inside the `db` group (after `db_sync_zoho_org_ids`), add:

```python
@db.command("embed-pending")
@click.option("--batch-size", default=50, type=int)
def db_embed_pending(batch_size):
    """Embed all rows with NULL embeddings.

    Hits facts + conversation_turns + document_chunks.
    """
    from goldman.embeddings import EmbeddingClient, embed_pending_in
    from goldman_db.connection import app_conn
    from goldman_db.conversation_turns import ConversationTurnRepository
    from goldman_db.documents import DocumentChunkRepository
    from goldman_db.facts import FactRepository

    embedder = EmbeddingClient()
    with app_conn() as conn:
        summary = embed_pending_in(
            facts_repo=FactRepository(conn),
            turns_repo=ConversationTurnRepository(conn),
            chunks_repo=DocumentChunkRepository(conn),
            embedder=embedder,
            batch_size=batch_size,
        )

    click.echo(
        f"  ok embedded: "
        f"{summary['facts']} facts, "
        f"{summary['turns']} turns, "
        f"{summary['chunks']} chunks."
    )
```

- [ ] **Step 2: Verify**

```bash
python3 cli.py db embed-pending --help 2>&1 | head -8
```

Expected: help shows.

- [ ] **Step 3: Commit**

```bash
git add cli.py
git commit -m "CLI: add 'db embed-pending' (batch embed across facts/turns/chunks)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 23: Update .env.example

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Append**

Open `.env.example` and append at the bottom:

```bash

# ============================================================================
# Goldman Phase 2 — embeddings, summarisation, storage
# ============================================================================
# OpenAI for text-embedding-3-small (1536d). Same key HQ Hub / Atlas uses.
OPENAI_API_KEY=

# Anthropic key already set above (Phase 1) — reused for DocumentSummariser.

# Supabase Storage (service-role for goldman bucket access).
# URL = https://tjxngrplgiqicdorsjzr.supabase.co  (the HQ Hub project URL)
GOLDMAN_SUPABASE_URL=
# Service-role key (admin-level, NEVER commit). Find in Supabase dashboard
# -> Project Settings -> API -> service_role secret.
GOLDMAN_SUPABASE_SERVICE_KEY=
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "Document Phase 2 env vars (OpenAI key + Supabase Storage)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 24: Full regression sweep + Phase 2 acceptance

**Files:** (no code changes; checkpoint)

- [ ] **Step 1: Run the entire test suite**

```bash
cd ~/Desktop/Obsidian/Projects/zoho-invoice-agent && python3 -m pytest -v 2>&1 | tail -10
```

Expected: every test passes. Phase 0/1's 82 + Phase 2's new tests (~25). Total ~107.

- [ ] **Step 2: Verify CLI surface**

```bash
python3 cli.py --help 2>&1 | tail -25
```

Expected: command list includes onboard, sync, who, remember, recall, document, db, plus the Phase 0 commands.

- [ ] **Step 3: Live sanity check (without Liran-supplied keys)**

These commands should print clear errors if keys are missing — that's the contract:

```bash
unset OPENAI_API_KEY
python3 cli.py recall "test question" 2>&1 | tail -2
```

Expected: clear `EmbeddingConfigError: OPENAI_API_KEY not set.`

```bash
unset GOLDMAN_SUPABASE_URL GOLDMAN_SUPABASE_SERVICE_KEY
echo "test doc" > /tmp/goldman_test.txt
python3 cli.py document upload --entity amzg /tmp/goldman_test.txt 2>&1 | tail -2
rm /tmp/goldman_test.txt
```

Expected: `StorageConfigError`.

- [ ] **Step 4: Update memory**

Append to `~/.claude/projects/-Users-hamburg/memory/project_goldman.md` (under Status):

```markdown
- **Phase 2 code = COMPLETE.** Memory + documents shipped: ALTER goldman.facts (embedding + conflict_with), new tables goldman.{conversation_turns, documents, document_chunks, capabilities}, hybrid_search RPC with RRF, OpenAI text-embedding-3-small pipeline, Supabase Storage upload path, document chunking + Claude Haiku summarisation. CLI commands: remember, recall, document upload, document list, db embed-pending. Required env vars added: OPENAI_API_KEY, GOLDMAN_SUPABASE_URL, GOLDMAN_SUPABASE_SERVICE_KEY.
```

- [ ] **Step 5: When Liran provides OpenAI key + Storage creds**

(Not part of plan execution — this is operational guidance.) Liran will:
1. Add `OPENAI_API_KEY` (same one HQ Hub uses) to `.env`.
2. Add `GOLDMAN_SUPABASE_URL=https://tjxngrplgiqicdorsjzr.supabase.co` and `GOLDMAN_SUPABASE_SERVICE_KEY=<service-role from Supabase dashboard>` to `.env`.
3. Run `python3 cli.py db embed-pending` (will be no-op initially — no rows yet).
4. Upload a document: `python3 cli.py document upload --entity amzg path/to/contract.pdf` then `python3 cli.py db embed-pending`.
5. Test recall: `python3 cli.py recall "what did the accountant say about VAT?" --entity amzg`.

---

## Spec coverage cross-check

| Spec section | Covered by task(s) |
|---|---|
| §6.1 — conversation_turns | Tasks 3 (SQL), 10 (repo) |
| §6.1 — facts + supersedes_id + conflict_with | Tasks 2 (ALTER), 13 (extended repo) |
| §6.1 — documents + chunks | Tasks 4 (SQL), 11 (repos), 17 (upload flow) |
| §6.1 — capabilities | Tasks 5 (SQL), 8 (seed), 12 (repo) |
| §6.3 — hybrid retrieval (vector + keyword + RRF) | Tasks 6 (RPC), 18 (Python wrapper) |
| §6.4 — embed pipeline (lossless subset) | Tasks 14 (EmbeddingClient + worker), 22 (CLI) |
| §6.4 — dedup/content-hash on facts | Phase 1 (already in place) |
| §11 — defaults (OpenAI text-embedding-3-small) | Task 14 (DEFAULT_MODEL constant) |
| Document storage location (Supabase Storage) | Tasks 7 (bucket), 16 (client), 17 (upload) |
| Document chunking (512 / 64 overlap) | Task 15 (chunker), 17 (upload flow defaults) |

All Phase 2 spec requirements have at least one implementing task.

---

## What's intentionally NOT in this plan

- pg_cron for embed pipeline — Phase 3+ ops; for now manual `db embed-pending`.
- Vendor email intake / Claude vision parser — Phase 3.
- Three-write filing pipeline (Supabase → Drive → Zoho Expenses) — Phase 3.
- Telegram bot — Phase 4 (will use `conversation_turns` heavily).
- Claude Code plugin — Phase 5.
- Auto conflict detection on fact write — Phase 6.
- Document summarisation with prompt caching — optimisation, not Phase 2.
- Hybrid search ANALYZE/VACUUM tuning — operational, not Phase 2.
