-- Goldman capabilities: developer-curated registry of what Goldman CAN DO.
-- Distinct from learned knowledge. Phase 4 Telegram bot + Phase 5 Claude
-- plugin both reference this for capability discovery.

CREATE TABLE IF NOT EXISTS goldman.capabilities (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT         NOT NULL UNIQUE,
    description TEXT         NOT NULL,
    kind        TEXT         NOT NULL CHECK (kind IN ('tool', 'skill', 'jurisdiction', 'api')),
    payload     JSONB        NOT NULL DEFAULT '{}',
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_goldman_capabilities_kind
    ON goldman.capabilities(kind) WHERE is_active = true;

DROP TRIGGER IF EXISTS trg_capabilities_updated_at ON goldman.capabilities;
CREATE TRIGGER trg_capabilities_updated_at
    BEFORE UPDATE ON goldman.capabilities
    FOR EACH ROW EXECUTE FUNCTION goldman.set_updated_at();
