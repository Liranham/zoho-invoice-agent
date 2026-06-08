-- Goldman facts: append-only structured facts.
-- Per spec §6.1 — corrections via supersedes_id, never UPDATE.
-- Phase 2 will ALTER to add: embedding column, conflict_with[], capabilities table.

CREATE TABLE IF NOT EXISTS goldman.facts (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id     UUID         REFERENCES goldman.entities(id),   -- nullable for cross-entity
    kind          TEXT         NOT NULL CHECK (kind IN (
        'target', 'preference', 'constraint',
        'commitment', 'event', 'decision', 'note'
    )),
    fact          TEXT         NOT NULL,
    content_hash  TEXT         NOT NULL,                          -- sha256 of normalized fact
    supersedes_id UUID         REFERENCES goldman.facts(id),
    source        TEXT         NOT NULL DEFAULT 'user_explicit' CHECK (source IN (
        'user_explicit', 'extracted', 'data_derived'
    )),
    seen_count    INTEGER      NOT NULL DEFAULT 1,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (entity_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_goldman_facts_entity
    ON goldman.facts(entity_id);
CREATE INDEX IF NOT EXISTS idx_goldman_facts_kind
    ON goldman.facts(kind);
CREATE INDEX IF NOT EXISTS idx_goldman_facts_supersedes
    ON goldman.facts(supersedes_id)
    WHERE supersedes_id IS NOT NULL;

-- "Live" view: leaf rows of supersedes chains.
CREATE OR REPLACE VIEW goldman.facts_live AS
SELECT f.*
FROM goldman.facts f
WHERE NOT EXISTS (
    SELECT 1 FROM goldman.facts f2 WHERE f2.supersedes_id = f.id
);

COMMENT ON TABLE goldman.facts IS
    'Append-only. Phase 2 adds embedding + conflict detection. Never UPDATE.';
