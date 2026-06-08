-- Goldman tax_registrations: append-only ledger of tax registrations per entity.
-- Per spec §5.2 — corrections via supersedes_id, never UPDATE.

CREATE TABLE IF NOT EXISTS goldman.tax_registrations (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id           UUID         NOT NULL REFERENCES goldman.entities(id),
    tax_type            TEXT         NOT NULL CHECK (tax_type IN (
        'vat', 'sales_tax', 'profits_tax', 'income_tax',
        'withholding_tax', 'payroll_tax', 'other'
    )),
    jurisdiction        TEXT         NOT NULL,   -- e.g. 'HK', 'GB', 'US-TX'
    registration_number TEXT,                    -- e.g. 'GB123456789'
    effective_from      DATE,
    effective_to        DATE,                    -- NULL = still active
    filing_cadence      TEXT         CHECK (filing_cadence IN (
        'monthly', 'quarterly', 'annual', 'irregular'
    ) OR filing_cadence IS NULL),
    notes               TEXT,
    supersedes_id       UUID         REFERENCES goldman.tax_registrations(id),
    source              TEXT         NOT NULL DEFAULT 'user_explicit' CHECK (source IN (
        'user_explicit', 'extracted', 'data_derived'
    )),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_goldman_tax_reg_entity
    ON goldman.tax_registrations(entity_id);
CREATE INDEX IF NOT EXISTS idx_goldman_tax_reg_supersedes
    ON goldman.tax_registrations(supersedes_id)
    WHERE supersedes_id IS NOT NULL;

-- "Live" view: rows that are not superseded by anything.
CREATE OR REPLACE VIEW goldman.tax_registrations_live AS
SELECT tr.*
FROM goldman.tax_registrations tr
WHERE NOT EXISTS (
    SELECT 1 FROM goldman.tax_registrations tr2
    WHERE tr2.supersedes_id = tr.id
);

COMMENT ON TABLE goldman.tax_registrations IS
    'Append-only. Corrections create new rows via supersedes_id. Never UPDATE.';
