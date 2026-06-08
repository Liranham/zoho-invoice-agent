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
