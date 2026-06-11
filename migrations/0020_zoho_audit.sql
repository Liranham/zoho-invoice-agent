-- Phase 9 — Zoho safety audit trail.
-- Every Zoho call (read or write) lands here so Liran can review what
-- Goldman touched, in which company, and whether it was executed or blocked.

CREATE TABLE IF NOT EXISTS goldman.zoho_audit (
    id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_slug           TEXT         NOT NULL,
    entity_legal_name     TEXT         NOT NULL,
    zoho_organization_id  TEXT         NOT NULL,
    tool_name             TEXT         NOT NULL,
    arguments             JSONB        NOT NULL DEFAULT '{}'::jsonb,
    status                TEXT         NOT NULL
        CHECK (status IN ('executed', 'blocked_unconfirmed',
                          'blocked_ambiguous', 'blocked_no_creds', 'error')),
    result_summary        TEXT,
    channel_id            TEXT,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_goldman_zoho_audit_entity
    ON goldman.zoho_audit(entity_slug, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_goldman_zoho_audit_status
    ON goldman.zoho_audit(status)
    WHERE status != 'executed';

COMMENT ON TABLE goldman.zoho_audit IS
    'Every Zoho Books call Goldman makes — read and write. Status tracks whether the call was executed, blocked (unconfirmed write / ambiguous entity / missing creds), or errored.';
