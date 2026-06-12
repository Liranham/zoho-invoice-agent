-- Phase 10 follow-up: persist the rolling Hubstaff refresh token.
--
-- Hubstaff PATs rotate on every exchange. Without persistence, the
-- env-var PAT goes stale on the first refresh and Render breaks at
-- the next process restart. This single-row table holds the latest
-- known refresh token so client startup can pick it up.

CREATE TABLE IF NOT EXISTS goldman.hubstaff_tokens (
    id              INT          PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    refresh_token   TEXT         NOT NULL,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
