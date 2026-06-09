-- Phase 6.1: extend goldman.documents to support knowledge_pack source.
-- Per spec §2 — additive only, no row touched.

-- 1) Drop the existing source CHECK (whatever Postgres named it).
DO $$
DECLARE
    cname TEXT;
BEGIN
    SELECT conname INTO cname
    FROM pg_constraint c
    JOIN pg_class t ON c.conrelid = t.oid
    JOIN pg_namespace n ON t.relnamespace = n.oid
    WHERE n.nspname = 'goldman'
      AND t.relname  = 'documents'
      AND c.contype  = 'c'
      AND pg_get_constraintdef(c.oid) ILIKE '%source%';
    IF cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE goldman.documents DROP CONSTRAINT %I', cname);
    END IF;
END$$;

-- 2) Re-add with the expanded enum.
ALTER TABLE goldman.documents
    ADD CONSTRAINT documents_source_check
    CHECK (source IN ('uploaded', 'email', 'manual', 'knowledge_pack'));

-- 3) Pack metadata columns (nullable; only set for knowledge_pack rows).
ALTER TABLE goldman.documents
    ADD COLUMN IF NOT EXISTS pack_topic   TEXT,
    ADD COLUMN IF NOT EXISTS pack_version TEXT;

-- 4) Partial index for "list packs by topic" queries.
CREATE INDEX IF NOT EXISTS idx_goldman_documents_pack_topic
    ON goldman.documents(pack_topic)
    WHERE pack_topic IS NOT NULL;
