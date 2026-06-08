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
