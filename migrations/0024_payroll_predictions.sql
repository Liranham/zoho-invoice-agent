-- Phase 12 — store Goldman's payroll PREDICTION so the reconciliation
-- step (10th / 25th) can compare it against the ACTUAL Wise outflows.

CREATE TABLE IF NOT EXISTS goldman.payroll_predictions (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id           UUID         NOT NULL REFERENCES goldman.entities(id),
    period_start        DATE         NOT NULL,
    period_stop         DATE         NOT NULL,
    -- Per-member breakdown: [{user_id, name, hours, rate, amount}, …]
    breakdown           JSONB        NOT NULL DEFAULT '[]'::jsonb,
    total_amount        NUMERIC(12,2) NOT NULL,
    currency            TEXT         NOT NULL DEFAULT 'USD',
    -- Reconciliation state.
    reconciled_at       TIMESTAMPTZ,
    actual_amount       NUMERIC(12,2),
    delta_amount        NUMERIC(12,2),
    reconciliation_note TEXT,
    -- Audit.
    source_reminder_id  UUID         REFERENCES goldman.scheduled_reminders(id),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (entity_id, period_start, period_stop)
);

CREATE INDEX IF NOT EXISTS idx_goldman_payroll_pred_period
    ON goldman.payroll_predictions(entity_id, period_stop DESC);
CREATE INDEX IF NOT EXISTS idx_goldman_payroll_pred_unreconciled
    ON goldman.payroll_predictions(period_stop)
    WHERE reconciled_at IS NULL;

DROP TRIGGER IF EXISTS trg_payroll_predictions_updated_at
    ON goldman.payroll_predictions;
CREATE TRIGGER trg_payroll_predictions_updated_at
    BEFORE UPDATE ON goldman.payroll_predictions
    FOR EACH ROW
    EXECUTE FUNCTION goldman.set_updated_at();

COMMENT ON TABLE goldman.payroll_predictions IS
    'Goldman saves his predicted payroll total when he sends a reminder. The reconciliation reminder (10th / 25th) compares it against actual Wise outflows from Gmail and flags any delta.';
