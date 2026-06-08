-- Goldman bank_accounts: bank + fintech accounts per entity.
-- Per spec §5.2 — manual entry in v1; live Wise sync deferred to Phase 6.

CREATE TABLE IF NOT EXISTS goldman.bank_accounts (
    id                 UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id          UUID         NOT NULL REFERENCES goldman.entities(id),
    provider           TEXT         NOT NULL,           -- 'Wise', 'HSBC', 'Chase', etc.
    account_label      TEXT         NOT NULL,           -- 'Wise USD Operating'
    currency           TEXT         NOT NULL,
    account_identifier TEXT,                            -- masked, e.g. '****1234'
    last_balance       NUMERIC(14, 2),
    last_balance_at    TIMESTAMPTZ,
    notes              TEXT,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (entity_id, account_label)
);

CREATE INDEX IF NOT EXISTS idx_goldman_bank_entity
    ON goldman.bank_accounts(entity_id);

DROP TRIGGER IF EXISTS trg_bank_accounts_updated_at ON goldman.bank_accounts;
CREATE TRIGGER trg_bank_accounts_updated_at
    BEFORE UPDATE ON goldman.bank_accounts
    FOR EACH ROW
    EXECUTE FUNCTION goldman.set_updated_at();
