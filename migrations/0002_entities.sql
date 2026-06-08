-- Goldman entities table.
-- Per spec §5.1: parent-child legal entities, each with its own Zoho org.

CREATE TABLE IF NOT EXISTS goldman.entities (
    id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                  TEXT         NOT NULL UNIQUE,
    legal_name            TEXT         NOT NULL,
    jurisdiction          TEXT         NOT NULL,
    parent_entity_id      UUID         REFERENCES goldman.entities(id),
    company_number        TEXT,
    incorporation_date    DATE,
    registered_address    TEXT,
    fiscal_year_end       TEXT,   -- "MM-DD" format
    base_currency         TEXT         NOT NULL DEFAULT 'USD',
    zoho_organization_id  TEXT,
    zoho_credential_key   TEXT,   -- env var prefix, e.g. "AMZG", "SEO"
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE goldman.entities IS
    'Legal entities Goldman manages. Each row owns its own Zoho org and tax registrations.';

CREATE INDEX IF NOT EXISTS idx_goldman_entities_slug
    ON goldman.entities(slug);
CREATE INDEX IF NOT EXISTS idx_goldman_entities_parent
    ON goldman.entities(parent_entity_id)
    WHERE parent_entity_id IS NOT NULL;

-- Update trigger for updated_at
CREATE OR REPLACE FUNCTION goldman.set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_entities_updated_at ON goldman.entities;
CREATE TRIGGER trg_entities_updated_at
    BEFORE UPDATE ON goldman.entities
    FOR EACH ROW
    EXECUTE FUNCTION goldman.set_updated_at();
