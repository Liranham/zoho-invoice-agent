-- Phase 11 — actual recurring reminders, not just commitment-shaped facts.
--
-- One row per recurring reminder Liran sets. The daily 09:00 scheduler
-- checks every active row, fires anything whose next_due_date <= today,
-- and rolls next_due_date forward.

CREATE TABLE IF NOT EXISTS goldman.scheduled_reminders (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    name              TEXT         NOT NULL,
    entity_slug       TEXT,                            -- amzg / seo, or NULL
    -- Recurrence: only days-of-month-based for v1.
    days_of_month     INTEGER[]    NOT NULL,           -- e.g. {4, 19}
    -- Action: a handler key in goldman.reminders.actions
    action            TEXT         NOT NULL,
    action_params     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    -- Where the message lands.
    channel           TEXT         NOT NULL DEFAULT 'telegram',
    channel_id        TEXT         NOT NULL,
    -- State.
    active            BOOLEAN      NOT NULL DEFAULT TRUE,
    last_fired_at     TIMESTAMPTZ,
    next_due_date     DATE         NOT NULL,
    last_result_summary TEXT,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_goldman_reminders_due
    ON goldman.scheduled_reminders(next_due_date)
    WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_goldman_reminders_active
    ON goldman.scheduled_reminders(active, channel);

DROP TRIGGER IF EXISTS trg_scheduled_reminders_updated_at
    ON goldman.scheduled_reminders;
CREATE TRIGGER trg_scheduled_reminders_updated_at
    BEFORE UPDATE ON goldman.scheduled_reminders
    FOR EACH ROW
    EXECUTE FUNCTION goldman.set_updated_at();

COMMENT ON TABLE goldman.scheduled_reminders IS
    'Each row is an actual recurring reminder. The daily scheduler tick fires due rows and DMs Liran. Saving a memory fact is NOT enough.';
