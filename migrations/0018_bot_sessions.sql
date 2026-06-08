-- Goldman bot_sessions: per-chat state (current entity, last active).

CREATE TABLE IF NOT EXISTS goldman.bot_sessions (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    front_door      TEXT         NOT NULL CHECK (front_door IN ('telegram', 'claude_code')),
    chat_id         TEXT         NOT NULL,
    current_entity  TEXT,                                -- entity slug or NULL = cross-entity
    session_id     TEXT         NOT NULL,               -- rotates daily or on /reset
    last_active_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (front_door, chat_id)
);

CREATE INDEX IF NOT EXISTS idx_goldman_bot_sessions_chat
    ON goldman.bot_sessions(front_door, chat_id);
