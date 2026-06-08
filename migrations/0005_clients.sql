-- Goldman clients: synced from each entity's Zoho contacts, enriched with tier.
-- Per spec §5.2.

CREATE TABLE IF NOT EXISTS goldman.clients (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id         UUID         NOT NULL REFERENCES goldman.entities(id),
    zoho_contact_id   TEXT         NOT NULL,
    contact_name      TEXT         NOT NULL,
    company_name      TEXT,
    primary_email     TEXT,
    tier              TEXT         CHECK (tier IN ('a', 'b', 'c') OR tier IS NULL),
    primary_contact   TEXT,
    notes             TEXT,
    last_synced_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (entity_id, zoho_contact_id)
);

CREATE INDEX IF NOT EXISTS idx_goldman_clients_entity
    ON goldman.clients(entity_id);
CREATE INDEX IF NOT EXISTS idx_goldman_clients_zoho
    ON goldman.clients(entity_id, zoho_contact_id);

DROP TRIGGER IF EXISTS trg_clients_updated_at ON goldman.clients;
CREATE TRIGGER trg_clients_updated_at
    BEFORE UPDATE ON goldman.clients
    FOR EACH ROW
    EXECUTE FUNCTION goldman.set_updated_at();
