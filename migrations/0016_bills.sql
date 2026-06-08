-- Goldman bills: canonical record of every vendor bill that lands in Goldman.
-- Per spec §7 — three-write pipeline anchored here.

CREATE TABLE IF NOT EXISTS goldman.bills (
    id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id             UUID         NOT NULL REFERENCES goldman.entities(id),
    vendor_id             UUID         REFERENCES goldman.vendors(id),
    vendor_name_at_intake TEXT         NOT NULL,
    invoice_number        TEXT,
    invoice_date          DATE,
    amount                NUMERIC(14, 2) NOT NULL,
    currency              TEXT         NOT NULL,
    due_date              DATE,
    line_items            JSONB        NOT NULL DEFAULT '[]',
    tax_amount            NUMERIC(14, 2),
    idempotency_hash      TEXT         NOT NULL UNIQUE,
    original_filename     TEXT,
    -- Three-write progress
    in_storage            BOOLEAN      NOT NULL DEFAULT FALSE,
    storage_path          TEXT,
    in_drive              BOOLEAN      NOT NULL DEFAULT FALSE,
    drive_file_id         TEXT,
    drive_url             TEXT,
    in_zoho               BOOLEAN      NOT NULL DEFAULT FALSE,
    zoho_expense_id       TEXT,
    -- Decision audit
    auto_filed            BOOLEAN      NOT NULL DEFAULT FALSE,
    confirm_required      BOOLEAN      NOT NULL DEFAULT FALSE,
    confirm_reason        TEXT,
    -- Operational
    status                TEXT         NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'partial', 'complete', 'failed', 'discarded'
    )),
    last_write_attempt_at TIMESTAMPTZ,
    last_error            TEXT,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_goldman_bills_entity_status
    ON goldman.bills(entity_id, status);
CREATE INDEX IF NOT EXISTS idx_goldman_bills_vendor
    ON goldman.bills(vendor_id) WHERE vendor_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_goldman_bills_partial
    ON goldman.bills(last_write_attempt_at)
    WHERE status IN ('partial', 'pending') AND in_storage = true;

DROP TRIGGER IF EXISTS trg_bills_updated_at ON goldman.bills;
CREATE TRIGGER trg_bills_updated_at
    BEFORE UPDATE ON goldman.bills
    FOR EACH ROW EXECUTE FUNCTION goldman.set_updated_at();
