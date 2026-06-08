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
