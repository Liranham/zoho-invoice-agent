-- Goldman pending_confirmations: Telegram inline-keyboard state.
-- Phase 3 writes rows when trust gate says "confirm"; Phase 4 picks them up.

CREATE TABLE IF NOT EXISTS goldman.pending_confirmations (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    bill_id         UUID         NOT NULL REFERENCES goldman.bills(id) ON DELETE CASCADE,
    entity_id       UUID         NOT NULL REFERENCES goldman.entities(id),
    prompt          TEXT         NOT NULL,
    options         JSONB        NOT NULL DEFAULT '[]',
    telegram_message_id BIGINT,                                     -- set after Telegram send
    answered_at     TIMESTAMPTZ,
    answer          TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_goldman_pending_open
    ON goldman.pending_confirmations(created_at)
    WHERE answered_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_goldman_pending_bill
    ON goldman.pending_confirmations(bill_id);
