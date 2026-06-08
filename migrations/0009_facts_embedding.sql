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

-- Phase 1's facts_live view was created with SELECT f.* which Postgres
-- materialised at creation time. Drop + recreate to pick up the new
-- embedding + conflict_with columns.
DROP VIEW IF EXISTS goldman.facts_live;
CREATE VIEW goldman.facts_live AS
SELECT f.*
FROM goldman.facts f
WHERE NOT EXISTS (
    SELECT 1 FROM goldman.facts f2 WHERE f2.supersedes_id = f.id
);
