-- Phase 10 — Hubstaff payroll connector

-- Per-member pay rate (Hubstaff API doesn't expose rates on the current
-- scope, so Goldman stores them here as Liran shares them).
CREATE TABLE IF NOT EXISTS goldman.hubstaff_member_rates (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id         UUID         NOT NULL REFERENCES goldman.entities(id),
    hubstaff_user_id  BIGINT       NOT NULL,
    full_name         TEXT         NOT NULL,
    rate_amount       NUMERIC(10,4) NOT NULL,
    rate_currency     TEXT         NOT NULL DEFAULT 'USD',
    rate_unit         TEXT         NOT NULL DEFAULT 'hour'
        CHECK (rate_unit IN ('hour', 'day', 'month', 'week')),
    effective_from    DATE,
    notes             TEXT,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (entity_id, hubstaff_user_id)
);

CREATE INDEX IF NOT EXISTS idx_hubstaff_rates_entity
    ON goldman.hubstaff_member_rates(entity_id);

-- Audit trail for every Hubstaff call (read or write).
CREATE TABLE IF NOT EXISTS goldman.hubstaff_audit (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_slug     TEXT         NOT NULL,
    org_id          TEXT         NOT NULL,
    tool_name       TEXT         NOT NULL,
    arguments       JSONB        NOT NULL DEFAULT '{}'::jsonb,
    status          TEXT         NOT NULL
        CHECK (status IN ('executed', 'error', 'blocked_no_creds')),
    result_summary  TEXT,
    channel_id      TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_hubstaff_audit_entity
    ON goldman.hubstaff_audit(entity_slug, created_at DESC);

COMMENT ON TABLE goldman.hubstaff_member_rates IS
    'Per-contractor hourly rate. Hubstaff API does not expose pay rates on the standard read scope, so Goldman keeps them here.';
COMMENT ON TABLE goldman.hubstaff_audit IS
    'Every Hubstaff API call Goldman makes — for review and debugging.';
