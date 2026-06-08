-- Goldman schema & isolation defenses.
-- Per spec §6.5: dedicated schema, restricted role, REVOKE ALL on public.

-- 1. Schema
CREATE SCHEMA IF NOT EXISTS goldman;
COMMENT ON SCHEMA goldman IS 'Goldman CFO agent — isolated from HQ Hub public schema.';

-- 2. Restricted runtime role
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'goldman_app') THEN
        CREATE ROLE goldman_app NOLOGIN;
    END IF;
END$$;

-- 3. Grants: goldman_app can use the goldman schema, nothing else.
GRANT USAGE ON SCHEMA goldman TO goldman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA goldman TO goldman_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA goldman TO goldman_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA goldman
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO goldman_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA goldman
    GRANT USAGE, SELECT ON SEQUENCES TO goldman_app;

-- 4. Hard isolation: explicitly REVOKE any inherited public access.
REVOKE ALL ON SCHEMA public FROM goldman_app;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM goldman_app;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM goldman_app;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM goldman_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL ON TABLES FROM goldman_app;

-- 5. Auth login role for runtime (Supabase pattern: a login user that
--    inherits goldman_app). Created without password — Supabase admin
--    rotates the password out-of-band; the connection URL embeds it.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'goldman_app_login') THEN
        CREATE ROLE goldman_app_login LOGIN INHERIT;
        GRANT goldman_app TO goldman_app_login;
    END IF;
END$$;
