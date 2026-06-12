-- Phase 13 — audit trail for every Wise API call Goldman makes.
-- Wise reads are sensitive (balances, transfers, recipients) so every
-- call gets a row for forensic review. Pattern mirrors hubstaff_audit
-- and zoho_audit.

CREATE TABLE IF NOT EXISTS goldman.wise_audit (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id      TEXT,
    tool_name       TEXT         NOT NULL,
    arguments       JSONB        NOT NULL DEFAULT '{}'::jsonb,
    status          TEXT         NOT NULL
        CHECK (status IN ('executed', 'error', 'blocked_no_creds')),
    result_summary  TEXT,
    channel_id      TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wise_audit_created
    ON goldman.wise_audit(created_at DESC);

-- Cached business profile id so we don't have to call /v1/profiles every
-- request. Single-row table.
CREATE TABLE IF NOT EXISTS goldman.wise_config (
    id              INT          PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    profile_id      TEXT,
    profile_name    TEXT,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE goldman.wise_audit IS
    'Every Wise API call — for forensic review. Wise reads are sensitive.';
COMMENT ON TABLE goldman.wise_config IS
    'Cached Wise business profile id. Discovered once via /v1/profiles, reused.';
