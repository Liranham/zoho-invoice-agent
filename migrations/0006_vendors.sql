-- Goldman vendors: from Zoho contacts + recurring-expense detection.
-- Per spec §5.2 — supports trust-gate decisions in Phase 3.

CREATE TABLE IF NOT EXISTS goldman.vendors (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id         UUID         NOT NULL REFERENCES goldman.entities(id),
    zoho_contact_id   TEXT,                       -- nullable; vendor may not be in Zoho yet
    vendor_name       TEXT         NOT NULL,
    email_domain      TEXT,                       -- for fuzzy match on inbound bills
    category          TEXT         CHECK (category IN (
        'hosting', 'factory', 'shipping', 'software',
        'professional_services', 'utilities', 'other'
    ) OR category IS NULL),
    typical_amount    NUMERIC(14, 2),
    typical_currency  TEXT,
    typical_cadence   TEXT         CHECK (typical_cadence IN (
        'weekly', 'monthly', 'quarterly', 'annual', 'irregular'
    ) OR typical_cadence IS NULL),
    always_confirm    BOOLEAN      NOT NULL DEFAULT FALSE,
    last_seen_at      TIMESTAMPTZ,
    seen_count        INTEGER      NOT NULL DEFAULT 0,
    notes             TEXT,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (entity_id, vendor_name)
);

CREATE INDEX IF NOT EXISTS idx_goldman_vendors_entity
    ON goldman.vendors(entity_id);
CREATE INDEX IF NOT EXISTS idx_goldman_vendors_zoho
    ON goldman.vendors(entity_id, zoho_contact_id)
    WHERE zoho_contact_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_goldman_vendors_domain
    ON goldman.vendors(email_domain)
    WHERE email_domain IS NOT NULL;

DROP TRIGGER IF EXISTS trg_vendors_updated_at ON goldman.vendors;
CREATE TRIGGER trg_vendors_updated_at
    BEFORE UPDATE ON goldman.vendors
    FOR EACH ROW
    EXECUTE FUNCTION goldman.set_updated_at();
