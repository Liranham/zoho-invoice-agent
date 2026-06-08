# Goldman Phase 0 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Foundation refactor — repo rename, multi-entity Zoho factory, `goldman` Postgres schema with hard isolation, `entities` table seeded with both companies. No behavioural regressions for existing CLI commands; all green tests.

**Architecture:** Three layers of change in dependency order — (1) Postgres foundation (schema, role, isolation defenses, `entities` table) accessed via a Goldman-owned migrator + connection pool, (2) Zoho refactor into a per-entity factory wrapping the existing `ZohoClient`, (3) CLI/main wiring so every operation routes through the factory by entity slug. Repo + Render rename done LAST, after all code is verified.

**Tech Stack:** Python 3.11+, `psycopg[binary]` 3.x (new dependency for direct Postgres), existing `requests`, `click`, `pytest`, `python-dotenv`. Postgres = HQ Hub Supabase project (`tjxngrplgiqicdorsjzr`) with hard schema isolation. No PostgREST — Goldman uses raw SQL via psycopg, never through Supabase's HTTP API.

---

## File Map

**Create:**
- `migrations/0001_goldman_schema.sql` — creates `goldman` schema, `goldman_app` role, `REVOKE ALL ON SCHEMA public FROM goldman_app`, internal `goldman.migrations` table.
- `migrations/0002_entities.sql` — `goldman.entities` table.
- `migrations/0003_seed_entities.sql` — seeds AMZ Expert Global Limited + Specific Edge Outsourcing LLC.
- `goldman_db/__init__.py` — package marker.
- `goldman_db/connection.py` — `get_admin_conn()` and `get_app_conn()` context managers using `psycopg.connect()`.
- `goldman_db/migrator.py` — applies pending `.sql` files from `migrations/` in filename order; idempotent.
- `goldman_db/entities.py` — `Entity` dataclass + `EntityRepository` with `list_all()`, `get_by_slug()`, `get_by_id()`.
- `goldman/__init__.py` — top-level package marker.
- `goldman/zoho.py` — `for_entity(slug)` factory returning a fully wired `ZohoClient`.
- `tests/test_goldman_migrator.py` — TDD coverage of migrator behaviour.
- `tests/test_goldman_entities_repo.py` — TDD coverage of EntityRepository.
- `tests/test_goldman_zoho_factory.py` — TDD coverage of `for_entity()`.

**Modify:**
- `requirements.txt` — add `psycopg[binary]>=3.1`.
- `config/settings.py` — replace single `ZohoAuthSettings` with `entity_zoho_credentials(slug)`; add `GoldmanDbSettings`.
- `cli.py` — every command gains `--entity` flag (default `amzg`); routes via `goldman.zoho.for_entity()`.
- `main.py` — server mode initialises per-entity service maps; `_invoice_service` becomes `_invoice_services: dict[slug → InvoiceService]`.
- `.env.example` — multi-entity Zoho env vars, `GOLDMAN_DB_URL`, deprecation comment for old single-entity vars.
- `README.md` — short note that multi-entity is the new default.

**Rename (LAST — after all tests pass):**
- Filesystem: `~/Desktop/Obsidian/Projects/zoho-invoice-agent` → `~/Desktop/Obsidian/Projects/goldman`
- GitHub: `Liranham/zoho-invoice-agent` → `Liranham/goldman`
- Render: service name `zoho-invoice-agent` → `goldman` (URL changes)
- `render.yaml`: `name`, `repo` URL updated

---

## Task 1: Add psycopg dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add psycopg to requirements**

Open `requirements.txt` and add this line after `cryptography>=41.0.0`:

```
psycopg[binary]>=3.1.0
```

- [ ] **Step 2: Install locally**

Run from repo root:
```bash
pip install -r requirements.txt
```

Expected: pip resolves and installs `psycopg-binary` without error. No version conflicts.

- [ ] **Step 3: Verify import works**

Run:
```bash
python -c "import psycopg; print(psycopg.__version__)"
```

Expected: prints a version like `3.1.18`. No ImportError.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "Add psycopg dependency for Goldman DB access

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Goldman DB settings

**Files:**
- Modify: `config/settings.py`
- Test: (no unit test — pure dataclass; covered by integration tests later)

- [ ] **Step 1: Add `GoldmanDbSettings` dataclass to settings.py**

In `config/settings.py`, add this dataclass between `TelegramSettings` and the root `Settings` class:

```python
@dataclass
class GoldmanDbSettings:
    """Goldman Postgres (Supabase) configuration.

    Two roles:
    - admin_url: super-admin / service-role connection used by migrations and
      one-off admin scripts. Should NOT be used at runtime.
    - app_url: connection authenticated as goldman_app — restricted role with
      REVOKE ALL on public.*. This is what Goldman's code uses at runtime.
    """

    admin_url: str = ""
    app_url: str = ""

    def __post_init__(self):
        self.admin_url = os.getenv("GOLDMAN_DB_ADMIN_URL", "")
        self.app_url = os.getenv("GOLDMAN_DB_APP_URL", "")
```

- [ ] **Step 2: Wire it into the root Settings**

In the same file, modify the root `Settings` dataclass to add a `goldman_db` field. Change:

```python
@dataclass
class Settings:
    """Root settings container."""

    zoho_auth: ZohoAuthSettings = field(default_factory=ZohoAuthSettings)
    invoice_defaults: InvoiceDefaults = field(default_factory=InvoiceDefaults)
    scheduler: SchedulerSettings = field(default_factory=SchedulerSettings)
    gmail: GmailSettings = field(default_factory=GmailSettings)
    telegram: TelegramSettings = field(default_factory=TelegramSettings)
    wise: WiseSettings = field(default_factory=WiseSettings)
```

to:

```python
@dataclass
class Settings:
    """Root settings container."""

    zoho_auth: ZohoAuthSettings = field(default_factory=ZohoAuthSettings)
    invoice_defaults: InvoiceDefaults = field(default_factory=InvoiceDefaults)
    scheduler: SchedulerSettings = field(default_factory=SchedulerSettings)
    gmail: GmailSettings = field(default_factory=GmailSettings)
    telegram: TelegramSettings = field(default_factory=TelegramSettings)
    wise: WiseSettings = field(default_factory=WiseSettings)
    goldman_db: GoldmanDbSettings = field(default_factory=GoldmanDbSettings)
```

- [ ] **Step 3: Verify the settings load**

Run:
```bash
python -c "from config.settings import Settings; s = Settings(); print('admin:', bool(s.goldman_db.admin_url), 'app:', bool(s.goldman_db.app_url))"
```

Expected (without env vars set): `admin: False app: False`. No traceback.

- [ ] **Step 4: Commit**

```bash
git add config/settings.py
git commit -m "Add GoldmanDbSettings for Postgres admin + app URLs

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Goldman DB connection module

**Files:**
- Create: `goldman_db/__init__.py`
- Create: `goldman_db/connection.py`
- Test: (deferred to Task 4 where migrator exercises it)

- [ ] **Step 1: Create the package marker**

Create `goldman_db/__init__.py` containing exactly:

```python
"""Goldman Postgres access layer.

Two roles:
- admin connection: schema migrations and one-off ops (super-admin / service-role).
- app connection: restricted role goldman_app — what runtime code uses.

Always prefer the app connection. Reach for admin only inside migrate.py
or explicit admin scripts.
"""
```

- [ ] **Step 2: Create the connection module**

Create `goldman_db/connection.py` containing exactly:

```python
"""Postgres connection helpers for Goldman.

Returns plain psycopg.Connection objects via context managers.
Connection strings are read from GoldmanDbSettings at call time so tests
can override env vars before each call.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import psycopg

from config.settings import GoldmanDbSettings

logger = logging.getLogger(__name__)


def _connect(url: str, role_label: str) -> psycopg.Connection:
    if not url:
        raise RuntimeError(
            f"Goldman DB {role_label} URL not configured. "
            f"Set GOLDMAN_DB_{role_label.upper()}_URL."
        )
    conn = psycopg.connect(url, autocommit=False)
    return conn


@contextmanager
def admin_conn() -> Iterator[psycopg.Connection]:
    """Yield an admin (super-admin / service-role) connection.

    Use only in migrator and admin scripts. Commits on success, rolls back
    on exception.
    """
    settings = GoldmanDbSettings()
    conn = _connect(settings.admin_url, "admin")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def app_conn() -> Iterator[psycopg.Connection]:
    """Yield an app (goldman_app role) connection — the default for runtime."""
    settings = GoldmanDbSettings()
    conn = _connect(settings.app_url, "app")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

- [ ] **Step 3: Verify import works**

Run:
```bash
python -c "from goldman_db.connection import admin_conn, app_conn; print('OK')"
```

Expected: prints `OK`. No ImportError.

- [ ] **Step 4: Commit**

```bash
git add goldman_db/__init__.py goldman_db/connection.py
git commit -m "Add Goldman DB connection helpers (admin + app roles)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Goldman migrator (TDD)

**Files:**
- Create: `goldman_db/migrator.py`
- Test: `tests/test_goldman_migrator.py`

The migrator scans `migrations/` for `*.sql` files, sorts them by filename, and applies any not yet recorded in `goldman.migrations`. If `goldman.migrations` doesn't exist yet, the migrator applies the first file (which must create the table) and bootstraps tracking after.

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_migrator.py` containing:

```python
"""Tests for the Goldman migrator.

Uses an in-memory fake Postgres connection (psycopg-style cursor mock) to
verify migration ordering, idempotency, and the bootstrap path where
goldman.migrations does not yet exist.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from goldman_db.migrator import _planned_migrations, apply_pending


def test_planned_migrations_sorts_by_filename(tmp_path: Path):
    (tmp_path / "0003_three.sql").write_text("-- three")
    (tmp_path / "0001_one.sql").write_text("-- one")
    (tmp_path / "0002_two.sql").write_text("-- two")
    (tmp_path / "ignored.txt").write_text("not sql")

    plan = _planned_migrations(tmp_path)

    assert [p.name for p in plan] == [
        "0001_one.sql",
        "0002_two.sql",
        "0003_three.sql",
    ]


def test_apply_pending_bootstraps_when_table_missing(tmp_path: Path):
    """First run: goldman.migrations doesn't exist; apply 0001 then record."""
    (tmp_path / "0001_init.sql").write_text("CREATE SCHEMA goldman;")

    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value

    # First fetchone() — table existence check — returns None (does not exist).
    # Second fetchone() — after we create migrations table — returns ().
    cur.fetchone.side_effect = [None, ()]
    cur.fetchall.return_value = []  # no rows in goldman.migrations after creation

    applied = apply_pending(conn, tmp_path)

    assert applied == ["0001_init.sql"]
    # Verify the SQL file content was executed
    assert any("CREATE SCHEMA goldman" in str(c) for c in cur.execute.call_args_list)


def test_apply_pending_skips_already_applied(tmp_path: Path):
    (tmp_path / "0001_one.sql").write_text("-- one")
    (tmp_path / "0002_two.sql").write_text("-- two")

    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value

    # Table exists; 0001 already applied
    cur.fetchone.return_value = (True,)
    cur.fetchall.return_value = [("0001_one.sql",)]

    applied = apply_pending(conn, tmp_path)

    assert applied == ["0002_two.sql"]


def test_apply_pending_records_each_migration(tmp_path: Path):
    (tmp_path / "0001_one.sql").write_text("SELECT 1;")

    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (True,)
    cur.fetchall.return_value = []

    apply_pending(conn, tmp_path)

    # Verify an INSERT into goldman.migrations was made for 0001_one.sql
    insert_calls = [
        c for c in cur.execute.call_args_list
        if "INSERT INTO goldman.migrations" in str(c)
    ]
    assert len(insert_calls) == 1
    assert "0001_one.sql" in str(insert_calls[0])
```

- [ ] **Step 2: Run the test to confirm failure**

Run:
```bash
pytest tests/test_goldman_migrator.py -v
```

Expected: All four tests fail with `ImportError: cannot import name '_planned_migrations' from 'goldman_db.migrator'` (or similar). The module doesn't exist yet.

- [ ] **Step 3: Implement the migrator**

Create `goldman_db/migrator.py` containing:

```python
"""Goldman migrator.

Applies pending .sql files from a migrations directory in filename order.
Tracked in goldman.migrations (created bootstrap-style when missing).

Designed for use with psycopg connections. The connection's transaction
boundary is the caller's responsibility — apply_pending uses one cursor
and commits at the end of each migration to preserve partial progress.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

import psycopg

logger = logging.getLogger(__name__)


_BOOTSTRAP_MIGRATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS goldman.migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _planned_migrations(migrations_dir: Path) -> list[Path]:
    """Return all .sql files in migrations_dir sorted by filename."""
    files = sorted(p for p in migrations_dir.iterdir() if p.suffix == ".sql")
    return files


def _migrations_table_exists(cur) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM pg_namespace n
        JOIN pg_class c ON c.relnamespace = n.oid
        WHERE n.nspname = 'goldman' AND c.relname = 'migrations'
        """
    )
    return cur.fetchone() is not None


def _already_applied(cur) -> set[str]:
    cur.execute("SELECT filename FROM goldman.migrations")
    return {row[0] for row in cur.fetchall()}


def apply_pending(
    conn: psycopg.Connection, migrations_dir: Path
) -> list[str]:
    """Apply any pending migrations. Returns the list of filenames applied."""
    plan = _planned_migrations(migrations_dir)
    if not plan:
        logger.info("No migration files found in %s", migrations_dir)
        return []

    applied: list[str] = []
    with conn.cursor() as cur:
        has_table = _migrations_table_exists(cur)

        if not has_table:
            # Bootstrap path: apply the first migration (which MUST create
            # the goldman schema), then create the migrations table, then
            # record the first migration.
            first = plan[0]
            logger.info("Bootstrap: applying %s", first.name)
            cur.execute(first.read_text())
            cur.execute(_BOOTSTRAP_MIGRATIONS_TABLE_SQL)
            cur.execute(
                "INSERT INTO goldman.migrations (filename) VALUES (%s)",
                (first.name,),
            )
            applied.append(first.name)
            conn.commit()
            plan = plan[1:]

        done = _already_applied(cur)
        for migration in plan:
            if migration.name in done:
                continue
            logger.info("Applying %s", migration.name)
            cur.execute(migration.read_text())
            cur.execute(
                "INSERT INTO goldman.migrations (filename) VALUES (%s)",
                (migration.name,),
            )
            applied.append(migration.name)
            conn.commit()

    return applied
```

- [ ] **Step 4: Run the tests — should pass**

Run:
```bash
pytest tests/test_goldman_migrator.py -v
```

Expected: All 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add goldman_db/migrator.py tests/test_goldman_migrator.py
git commit -m "Add Goldman migrator (idempotent SQL file applier)

Tracks applied migrations in goldman.migrations (created bootstrap-style
on first run). Tested for ordering, idempotency, and bootstrap behaviour.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Migration 0001 — goldman schema + role + isolation

**Files:**
- Create: `migrations/0001_goldman_schema.sql`

This migration creates the dedicated `goldman` Postgres schema, the restricted `goldman_app` role with `REVOKE ALL ON SCHEMA public FROM goldman_app`, and the GRANT on `goldman` schema.

- [ ] **Step 1: Create the SQL file**

Create `migrations/0001_goldman_schema.sql` containing exactly:

```sql
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
```

- [ ] **Step 2: Smoke-check the SQL parses**

Run:
```bash
python -c "
from pathlib import Path
sql = Path('migrations/0001_goldman_schema.sql').read_text()
print(f'{len(sql)} bytes, {sql.count(chr(10))} lines')
assert 'CREATE SCHEMA IF NOT EXISTS goldman' in sql
assert 'REVOKE ALL ON SCHEMA public FROM goldman_app' in sql
print('OK')
"
```

Expected: prints byte count + `OK`.

- [ ] **Step 3: Commit**

```bash
git add migrations/0001_goldman_schema.sql
git commit -m "Add migration 0001: goldman schema + isolation defenses

Creates dedicated 'goldman' Postgres schema, restricted goldman_app role
with REVOKE ALL on public.*, and a login role goldman_app_login that
inherits goldman_app. Per spec §6.5.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Migration 0002 — entities table

**Files:**
- Create: `migrations/0002_entities.sql`

- [ ] **Step 1: Create the SQL file**

Create `migrations/0002_entities.sql` containing exactly:

```sql
-- Goldman entities table.
-- Per spec §5.1: parent-child legal entities, each with its own Zoho org.

CREATE TABLE IF NOT EXISTS goldman.entities (
    id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                  TEXT         NOT NULL UNIQUE,
    legal_name            TEXT         NOT NULL,
    jurisdiction          TEXT         NOT NULL,
    parent_entity_id      UUID         REFERENCES goldman.entities(id),
    company_number        TEXT,
    incorporation_date    DATE,
    registered_address    TEXT,
    fiscal_year_end       TEXT,   -- "MM-DD" format
    base_currency         TEXT         NOT NULL DEFAULT 'USD',
    zoho_organization_id  TEXT,
    zoho_credential_key   TEXT,   -- env var prefix, e.g. "AMZG", "SEO"
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE goldman.entities IS
    'Legal entities Goldman manages. Each row owns its own Zoho org and tax registrations.';

CREATE INDEX IF NOT EXISTS idx_goldman_entities_slug
    ON goldman.entities(slug);
CREATE INDEX IF NOT EXISTS idx_goldman_entities_parent
    ON goldman.entities(parent_entity_id)
    WHERE parent_entity_id IS NOT NULL;

-- Update trigger for updated_at
CREATE OR REPLACE FUNCTION goldman.set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_entities_updated_at ON goldman.entities;
CREATE TRIGGER trg_entities_updated_at
    BEFORE UPDATE ON goldman.entities
    FOR EACH ROW
    EXECUTE FUNCTION goldman.set_updated_at();
```

- [ ] **Step 2: Smoke-check**

Run:
```bash
python -c "
from pathlib import Path
sql = Path('migrations/0002_entities.sql').read_text()
assert 'CREATE TABLE IF NOT EXISTS goldman.entities' in sql
assert 'parent_entity_id' in sql
assert 'zoho_organization_id' in sql
print('OK')
"
```

Expected: prints `OK`.

- [ ] **Step 3: Commit**

```bash
git add migrations/0002_entities.sql
git commit -m "Add migration 0002: goldman.entities table

Parent-child legal entities (HK → US), each with own Zoho org reference.
Includes updated_at trigger.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Migration 0003 — seed AMZ Expert Global + Specific Edge Outsourcing

**Files:**
- Create: `migrations/0003_seed_entities.sql`

- [ ] **Step 1: Create the seed SQL**

Create `migrations/0003_seed_entities.sql` containing exactly:

```sql
-- Seed Goldman's two known entities.
-- Idempotent via ON CONFLICT DO NOTHING on slug.

INSERT INTO goldman.entities (
    slug, legal_name, jurisdiction, base_currency,
    zoho_credential_key
) VALUES (
    'amzg',
    'AMZ Expert Global Limited',
    'HK',
    'HKD',
    'AMZG'
) ON CONFLICT (slug) DO NOTHING;

INSERT INTO goldman.entities (
    slug, legal_name, jurisdiction, base_currency,
    zoho_credential_key, parent_entity_id
) VALUES (
    'seo',
    'Specific Edge Outsourcing LLC',
    'US',
    'USD',
    'SEO',
    (SELECT id FROM goldman.entities WHERE slug = 'amzg')
) ON CONFLICT (slug) DO NOTHING;
```

Note: `zoho_organization_id`, `company_number`, `incorporation_date`, `registered_address`, `fiscal_year_end` are intentionally left NULL — they're filled in Phase 1 via the onboarding brain-dump (per spec §9). Phase 0 only needs the structural seed.

- [ ] **Step 2: Smoke-check**

Run:
```bash
python -c "
from pathlib import Path
sql = Path('migrations/0003_seed_entities.sql').read_text()
assert \"slug = 'amzg'\" in sql
assert 'AMZ Expert Global Limited' in sql
assert 'Specific Edge Outsourcing LLC' in sql
assert 'ON CONFLICT (slug) DO NOTHING' in sql
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add migrations/0003_seed_entities.sql
git commit -m "Add migration 0003: seed entities (amzg + seo)

Inserts AMZ Expert Global Limited (HK parent) and Specific Edge Outsourcing
LLC (US subsidiary). Tax registrations, addresses, etc. left NULL — filled
by Phase 1 onboarding.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Entity repository (TDD)

**Files:**
- Create: `goldman_db/entities.py`
- Test: `tests/test_goldman_entities_repo.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_entities_repo.py` containing:

```python
"""Tests for the Goldman EntityRepository."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from goldman_db.entities import Entity, EntityRepository


def _make_repo(rows):
    """Build an EntityRepository whose cursor returns the given rows."""
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = rows
    cur.fetchone.side_effect = rows if rows else [None]
    repo = EntityRepository(conn)
    return repo, conn, cur


def test_list_all_returns_entities():
    amzg_id = uuid4()
    seo_id = uuid4()
    repo, conn, cur = _make_repo([
        (amzg_id, "amzg", "AMZ Expert Global Limited", "HK", None, "HKD",
         None, "AMZG"),
        (seo_id, "seo", "Specific Edge Outsourcing LLC", "US", amzg_id, "USD",
         None, "SEO"),
    ])

    entities = repo.list_all()

    assert len(entities) == 2
    assert entities[0].slug == "amzg"
    assert entities[0].legal_name == "AMZ Expert Global Limited"
    assert entities[0].parent_entity_id is None
    assert entities[1].slug == "seo"
    assert entities[1].parent_entity_id == amzg_id


def test_get_by_slug_returns_entity():
    amzg_id = uuid4()
    repo, conn, cur = _make_repo([
        (amzg_id, "amzg", "AMZ Expert Global Limited", "HK", None, "HKD",
         None, "AMZG"),
    ])

    entity = repo.get_by_slug("amzg")

    assert entity is not None
    assert entity.slug == "amzg"
    assert entity.zoho_credential_key == "AMZG"


def test_get_by_slug_returns_none_when_missing():
    repo, conn, cur = _make_repo([])
    cur.fetchone.return_value = None

    entity = repo.get_by_slug("nope")

    assert entity is None


def test_get_by_slug_normalises_case():
    """slug lookup is case-insensitive (matches CLI convenience)."""
    amzg_id = uuid4()
    repo, conn, cur = _make_repo([
        (amzg_id, "amzg", "AMZ Expert Global Limited", "HK", None, "HKD",
         None, "AMZG"),
    ])

    entity = repo.get_by_slug("AMZG")

    assert entity is not None
    assert entity.slug == "amzg"
    # Verify the query used the lowercased value
    args = cur.execute.call_args[0]
    assert args[1] == ("amzg",)
```

- [ ] **Step 2: Run the test — confirm it fails**

Run:
```bash
pytest tests/test_goldman_entities_repo.py -v
```

Expected: `ImportError: cannot import name 'Entity' from 'goldman_db.entities'`.

- [ ] **Step 3: Implement EntityRepository**

Create `goldman_db/entities.py` containing:

```python
"""Read-only repository over goldman.entities.

Writes are limited to migrations + the Phase 1 onboarding flow; this module
exposes lookup paths only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import psycopg


_SELECT_COLS = """
    id, slug, legal_name, jurisdiction, parent_entity_id,
    base_currency, zoho_organization_id, zoho_credential_key
"""


@dataclass(frozen=True)
class Entity:
    id: UUID
    slug: str
    legal_name: str
    jurisdiction: str
    parent_entity_id: Optional[UUID]
    base_currency: str
    zoho_organization_id: Optional[str]
    zoho_credential_key: Optional[str]


def _row_to_entity(row) -> Entity:
    return Entity(
        id=row[0],
        slug=row[1],
        legal_name=row[2],
        jurisdiction=row[3],
        parent_entity_id=row[4],
        base_currency=row[5],
        zoho_organization_id=row[6],
        zoho_credential_key=row[7],
    )


class EntityRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def list_all(self) -> list[Entity]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_SELECT_COLS} FROM goldman.entities ORDER BY created_at"
            )
            return [_row_to_entity(row) for row in cur.fetchall()]

    def get_by_slug(self, slug: str) -> Optional[Entity]:
        normalised = slug.lower()
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_SELECT_COLS} FROM goldman.entities WHERE slug = %s",
                (normalised,),
            )
            row = cur.fetchone()
            return _row_to_entity(row) if row else None

    def get_by_id(self, entity_id: UUID) -> Optional[Entity]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_SELECT_COLS} FROM goldman.entities WHERE id = %s",
                (entity_id,),
            )
            row = cur.fetchone()
            return _row_to_entity(row) if row else None
```

- [ ] **Step 4: Run the tests — should pass**

Run:
```bash
pytest tests/test_goldman_entities_repo.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add goldman_db/entities.py tests/test_goldman_entities_repo.py
git commit -m "Add EntityRepository (list/get_by_slug/get_by_id)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: Multi-entity Zoho factory (TDD)

**Files:**
- Create: `goldman/__init__.py`
- Create: `goldman/zoho.py`
- Test: `tests/test_goldman_zoho_factory.py`

The factory takes an entity slug and returns a fully wired `ZohoClient` for that entity's Zoho org. It reads credentials from env vars keyed by `zoho_credential_key` (e.g. `ZOHO_AMZG_REFRESH_TOKEN`, `ZOHO_SEO_ORG_ID`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_zoho_factory.py` containing:

```python
"""Tests for the per-entity Zoho factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from goldman.zoho import (
    UnknownEntityError,
    MissingZohoCredentialsError,
    for_entity,
    invoice_service_for,
    contact_service_for,
    item_service_for,
)


@pytest.fixture(autouse=True)
def reset_factory_cache():
    """Clear the factory's per-process cache between tests."""
    from goldman.zoho import _client_cache
    _client_cache.clear()
    yield
    _client_cache.clear()


def _entity_repo_with(slug, cred_key, org_id):
    """Build a fake EntityRepository returning one entity."""
    from goldman_db.entities import Entity
    fake = MagicMock()
    fake.get_by_slug.return_value = Entity(
        id=uuid4(),
        slug=slug,
        legal_name=f"Test {slug.upper()}",
        jurisdiction="HK",
        parent_entity_id=None,
        base_currency="USD",
        zoho_organization_id=org_id,
        zoho_credential_key=cred_key,
    )
    return fake


def test_for_entity_returns_zoho_client(monkeypatch):
    monkeypatch.setenv("ZOHO_TEST_CLIENT_ID", "cid_test")
    monkeypatch.setenv("ZOHO_TEST_CLIENT_SECRET", "secret_test")
    monkeypatch.setenv("ZOHO_TEST_REFRESH_TOKEN", "refresh_test")

    repo = _entity_repo_with("amzg", "TEST", "org_42")

    client = for_entity("amzg", entity_repo=repo)

    assert client.organization_id == "org_42"
    assert client.auth.client_id == "cid_test"
    assert client.auth.refresh_token == "refresh_test"


def test_for_entity_caches_clients_per_slug(monkeypatch):
    monkeypatch.setenv("ZOHO_TEST_CLIENT_ID", "cid")
    monkeypatch.setenv("ZOHO_TEST_CLIENT_SECRET", "sec")
    monkeypatch.setenv("ZOHO_TEST_REFRESH_TOKEN", "rt")

    repo = _entity_repo_with("amzg", "TEST", "org_1")

    first = for_entity("amzg", entity_repo=repo)
    second = for_entity("amzg", entity_repo=repo)

    assert first is second  # cached


def test_for_entity_raises_for_unknown_slug():
    repo = MagicMock()
    repo.get_by_slug.return_value = None

    with pytest.raises(UnknownEntityError, match="nope"):
        for_entity("nope", entity_repo=repo)


def test_for_entity_raises_when_credentials_missing(monkeypatch):
    # Ensure env vars are NOT set
    monkeypatch.delenv("ZOHO_MISSING_CLIENT_ID", raising=False)
    monkeypatch.delenv("ZOHO_MISSING_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("ZOHO_MISSING_REFRESH_TOKEN", raising=False)

    repo = _entity_repo_with("amzg", "MISSING", "org_1")

    with pytest.raises(MissingZohoCredentialsError, match="MISSING"):
        for_entity("amzg", entity_repo=repo)


def test_invoice_service_for_returns_invoice_service(monkeypatch):
    monkeypatch.setenv("ZOHO_TEST_CLIENT_ID", "cid")
    monkeypatch.setenv("ZOHO_TEST_CLIENT_SECRET", "sec")
    monkeypatch.setenv("ZOHO_TEST_REFRESH_TOKEN", "rt")

    repo = _entity_repo_with("amzg", "TEST", "org_1")

    svc = invoice_service_for("amzg", entity_repo=repo)

    from zoho.invoices import InvoiceService
    assert isinstance(svc, InvoiceService)
```

- [ ] **Step 2: Run the test — confirm it fails**

Run:
```bash
pytest tests/test_goldman_zoho_factory.py -v
```

Expected: `ImportError: cannot import name 'for_entity' from 'goldman.zoho'`.

- [ ] **Step 3: Create the package marker**

Create `goldman/__init__.py` containing exactly:

```python
"""Goldman — CFO agent for AMZ Expert Global Limited + subsidiaries.

This package provides the per-entity Zoho factory and (in later phases)
the brain, document store, conversational layer, and front-door adapters.
"""
```

- [ ] **Step 4: Implement the factory**

Create `goldman/zoho.py` containing:

```python
"""Per-entity Zoho client factory.

Every Goldman operation routes through here. The factory:
  * Looks up the entity in goldman.entities.
  * Resolves env-var credentials by zoho_credential_key (e.g. ZOHO_AMZG_*).
  * Caches one ZohoClient per slug per process.

The shape mirrors the spec §5.3 — no global default Zoho ever again.
"""

from __future__ import annotations

import os
from typing import Optional

from auth.zoho_auth import ZohoAuth
from config.settings import GoldmanDbSettings
from goldman_db.connection import app_conn
from goldman_db.entities import EntityRepository
from zoho.client import ZohoClient
from zoho.contacts import ContactService
from zoho.invoices import InvoiceService
from zoho.items import ItemService


class GoldmanZohoError(Exception):
    """Base class for Goldman Zoho factory errors."""


class UnknownEntityError(GoldmanZohoError):
    """Raised when a slug doesn't match any row in goldman.entities."""


class MissingZohoCredentialsError(GoldmanZohoError):
    """Raised when an entity's Zoho env vars are not configured."""


_client_cache: dict[str, ZohoClient] = {}


def _env(key: str) -> str:
    return os.getenv(key, "")


def _resolve_credentials(cred_key: str) -> tuple[str, str, str, str, str]:
    """Return (client_id, client_secret, refresh_token, accounts_url, api_base_url)
    for the given credential key prefix (e.g. "AMZG" → ZOHO_AMZG_*)."""
    prefix = cred_key.upper()
    client_id = _env(f"ZOHO_{prefix}_CLIENT_ID")
    client_secret = _env(f"ZOHO_{prefix}_CLIENT_SECRET")
    refresh_token = _env(f"ZOHO_{prefix}_REFRESH_TOKEN")
    accounts_url = _env(f"ZOHO_{prefix}_ACCOUNTS_URL") or "https://accounts.zoho.com"
    api_base_url = _env(f"ZOHO_{prefix}_API_BASE_URL") or "https://www.zohoapis.com/books/v3"

    missing = [
        name for name, val in [
            (f"ZOHO_{prefix}_CLIENT_ID", client_id),
            (f"ZOHO_{prefix}_CLIENT_SECRET", client_secret),
            (f"ZOHO_{prefix}_REFRESH_TOKEN", refresh_token),
        ] if not val
    ]
    if missing:
        raise MissingZohoCredentialsError(
            f"Missing env vars for entity credential key {prefix!r}: "
            f"{', '.join(missing)}"
        )
    return client_id, client_secret, refresh_token, accounts_url, api_base_url


def _default_entity_repo() -> EntityRepository:
    """Build an EntityRepository from a fresh app DB connection.

    Note: caller is expected to keep this in a context — but the factory
    only uses it for the brief entity lookup, then closes the conn.
    """
    # Importing lazily so unit tests can pass a mocked repo without DB.
    raise NotImplementedError(
        "for_entity() requires an entity_repo argument in v0; "
        "DB-backed default will land alongside Phase 1."
    )


def for_entity(
    slug: str,
    *,
    entity_repo: Optional[EntityRepository] = None,
) -> ZohoClient:
    """Return a cached ZohoClient for the given entity slug.

    Raises UnknownEntityError if no entity with that slug exists,
    or MissingZohoCredentialsError if env vars aren't set.
    """
    normalised = slug.lower()

    if normalised in _client_cache:
        return _client_cache[normalised]

    repo = entity_repo or _default_entity_repo()
    entity = repo.get_by_slug(normalised)
    if entity is None:
        raise UnknownEntityError(f"No goldman.entities row with slug {slug!r}")

    if not entity.zoho_credential_key:
        raise MissingZohoCredentialsError(
            f"Entity {slug!r} has no zoho_credential_key set"
        )
    if not entity.zoho_organization_id:
        raise MissingZohoCredentialsError(
            f"Entity {slug!r} has no zoho_organization_id set"
        )

    (
        client_id, client_secret, refresh_token,
        accounts_url, api_base_url,
    ) = _resolve_credentials(entity.zoho_credential_key)

    auth = ZohoAuth(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        accounts_url=accounts_url,
    )
    client = ZohoClient(auth, api_base_url, entity.zoho_organization_id)
    _client_cache[normalised] = client
    return client


def invoice_service_for(
    slug: str,
    *,
    entity_repo: Optional[EntityRepository] = None,
) -> InvoiceService:
    return InvoiceService(for_entity(slug, entity_repo=entity_repo))


def contact_service_for(
    slug: str,
    *,
    entity_repo: Optional[EntityRepository] = None,
) -> ContactService:
    return ContactService(for_entity(slug, entity_repo=entity_repo))


def item_service_for(
    slug: str,
    *,
    entity_repo: Optional[EntityRepository] = None,
) -> ItemService:
    return ItemService(for_entity(slug, entity_repo=entity_repo))
```

- [ ] **Step 5: Update the test that exercises `for_entity` without `entity_repo`**

Re-check `tests/test_goldman_zoho_factory.py` — all tests should pass `entity_repo=repo` explicitly. The `_default_entity_repo()` path raises `NotImplementedError` which is intentional for Phase 0 (it gets wired up in Task 10 via a context-manager helper).

- [ ] **Step 6: Run the tests — should pass**

Run:
```bash
pytest tests/test_goldman_zoho_factory.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 7: Commit**

```bash
git add goldman/__init__.py goldman/zoho.py tests/test_goldman_zoho_factory.py
git commit -m "Add per-entity Zoho factory

for_entity(slug) looks up goldman.entities, resolves env-var creds by
zoho_credential_key prefix, returns a cached ZohoClient. Service helpers
(invoice_service_for, contact_service_for, item_service_for) build the
existing services on top. Raises typed errors for missing entities or creds.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: CLI entity routing

**Files:**
- Modify: `cli.py`

The existing `cli.py` builds one set of services from `Settings()` at command time. We change it so every command takes `--entity SLUG` (default `amzg`) and uses the factory.

- [ ] **Step 1: Read the existing cli.py to confirm line ranges**

Run:
```bash
wc -l cli.py
```

Expected: ~199 lines (matches current code).

- [ ] **Step 2: Replace `_build_services` with an entity-aware version**

Open `cli.py`. Replace the entire `_build_services()` function (currently around lines 26-44) with:

```python
def _build_services(entity_slug: str):
    """Build entity-scoped services using the Goldman Zoho factory.

    Each command receives an entity slug (CLI flag default = 'amzg').
    Routing through the factory guarantees no command silently hits
    the wrong Zoho organisation.
    """
    settings = Settings()
    # Settings.validate() is intentionally NOT called here — it validates
    # the legacy ZOHO_* singleton env vars, which we no longer rely on
    # for runtime ops. Validation now happens inside the factory per
    # zoho_credential_key.

    from goldman.zoho import (
        invoice_service_for, contact_service_for, item_service_for,
    )
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository

    # One DB lookup per command — small enough not to bother caching.
    with app_conn() as conn:
        repo = EntityRepository(conn)
        inv_svc = invoice_service_for(entity_slug, entity_repo=repo)
        contact_svc = contact_service_for(entity_slug, entity_repo=repo)
        item_svc = item_service_for(entity_slug, entity_repo=repo)
    return inv_svc, contact_svc, item_svc, settings
```

- [ ] **Step 3: Add `--entity` flag to every command**

For each Click command in `cli.py`, add a `--entity` option just before the function body. Pattern:

```python
@cli.command("list")
@click.option("--entity", default="amzg",
              help="Entity slug (amzg = AMZ Expert Global Ltd; seo = Specific Edge Outsourcing LLC)")
@click.option("--status", default="", help="Filter: draft, sent, paid, overdue")
@click.option("--page", default=1, type=int)
def list_invoices(entity, status, page):
    """List invoices."""
    inv_svc, _, _, _ = _build_services(entity)
    # ... rest unchanged
```

Apply this pattern to: `list_invoices`, `create`, `delete`, `batch_create`, `customers`, `create_customer`, `items`.

- [ ] **Step 4: Verify cli.py imports compile**

Run:
```bash
python -c "import cli; print('OK')"
```

Expected: `OK`. No ImportError.

- [ ] **Step 5: Smoke-check the help output for one command**

Run:
```bash
python cli.py list --help
```

Expected: shows `--entity TEXT` in the options list.

- [ ] **Step 6: Commit**

```bash
git add cli.py
git commit -m "CLI: route every command through Goldman entity factory

Every command accepts --entity SLUG (default 'amzg') and builds services
via goldman.zoho factory. No more silent dependence on global Settings
ZohoAuthSettings.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 11: main.py entity awareness

**Files:**
- Modify: `main.py`

The server-mode entrypoint also keeps a single global `_invoice_service`. Refactor to a dict keyed by slug, plus accept an `?entity=` query param on the HTTP endpoints.

- [ ] **Step 1: Change the global service refs**

In `main.py`, replace:

```python
# Global references for HTTP handler to use
_invoice_service = None
_gmail_automation = None
_wise_automation = None
_wise_signature_verifier = None
_telegram_notifier = None
```

with:

```python
# Global references for HTTP handler to use.
# _invoice_services is keyed by entity slug; pre-populated at startup.
_invoice_services: dict = {}  # slug -> InvoiceService
_gmail_automation = None
_wise_automation = None
_wise_signature_verifier = None
_telegram_notifier = None
```

- [ ] **Step 2: Update `_handle_list_invoices` to route by entity**

Replace the entire `_handle_list_invoices` method body with:

```python
    def _handle_list_invoices(self):
        if not _invoice_services:
            self._json_response(503, {"error": "service not ready"})
            return
        try:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            entity_slug = (qs.get("entity") or ["amzg"])[0].lower()
            svc = _invoice_services.get(entity_slug)
            if not svc:
                self._json_response(
                    400, {"error": f"unknown entity: {entity_slug}"}
                )
                return
            invoices = svc.list_invoices()
            self._json_response(
                200,
                {
                    "entity": entity_slug,
                    "invoices": [
                        {
                            "invoice_number": inv.invoice_number,
                            "status": inv.status,
                            "date": inv.date,
                            "total": inv.total,
                            "customer": inv.customer_name,
                        }
                        for inv in invoices
                    ],
                },
            )
        except Exception as e:
            self._json_response(500, {"error": str(e)})
```

- [ ] **Step 3: Update `_handle_create_invoice` to require entity in the body**

Replace the entire `_handle_create_invoice` method body with:

```python
    def _handle_create_invoice(self):
        if not _invoice_services:
            self._json_response(503, {"error": "service not ready"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}
            entity_slug = (body.get("entity") or "amzg").lower()
            svc = _invoice_services.get(entity_slug)
            if not svc:
                self._json_response(
                    400, {"error": f"unknown entity: {entity_slug}"}
                )
                return
            inv = svc.create_invoice(
                customer_id=body["customer_id"],
                line_items=body["line_items"],
                date=body.get("date", ""),
            )
            self._json_response(
                201,
                {
                    "entity": entity_slug,
                    "invoice_id": inv.invoice_id,
                    "invoice_number": inv.invoice_number,
                    "total": inv.total,
                },
            )
        except Exception as e:
            self._json_response(400, {"error": str(e)})
```

- [ ] **Step 4: Update `cmd_server` to populate `_invoice_services` per entity**

Inside `cmd_server`, replace:

```python
        auth = ZohoAuth(...)
        client = ZohoClient(...)
        _invoice_service = InvoiceService(client)
```

with:

```python
        from goldman.zoho import invoice_service_for
        from goldman_db.connection import app_conn
        from goldman_db.entities import EntityRepository

        with app_conn() as conn:
            repo = EntityRepository(conn)
            entities = repo.list_all()
            for entity in entities:
                if not entity.zoho_credential_key or not entity.zoho_organization_id:
                    logger.warning(
                        "Entity %s missing Zoho creds — skipping in services map",
                        entity.slug,
                    )
                    continue
                try:
                    _invoice_services[entity.slug] = invoice_service_for(
                        entity.slug, entity_repo=repo
                    )
                    logger.info("Wired Zoho services for entity %s", entity.slug)
                except Exception as svc_err:
                    logger.warning(
                        "Could not wire entity %s: %s", entity.slug, svc_err
                    )
```

Also remove the now-unused imports at the same site:
- `from auth.zoho_auth import ZohoAuth`
- `from zoho.client import ZohoClient`
- `from zoho.invoices import InvoiceService`

(Keep `from zoho.contacts import ContactService` — still used by Wise automation.)

For Wise automation that needs a single `client` and `contact_service`, switch to using the `amzg` entity explicitly (preserving existing behaviour — Wise webhooks currently fire for HK invoices):

```python
        # Initialize Wise automation if enabled
        if settings.wise.enabled:
            from wise.auth import WiseAuth
            from wise.client import WiseClient
            from wise.signature import SignatureVerifier
            from wise.handler import WiseAutomation
            from goldman.zoho import for_entity, contact_service_for

            wise_auth = WiseAuth.from_env_b64(
                settings.wise.api_token, settings.wise.private_key_b64
            )
            wise_client = WiseClient(wise_auth)
            _wise_signature_verifier = SignatureVerifier()
            with app_conn() as conn:
                repo = EntityRepository(conn)
                contact_service = contact_service_for("amzg", entity_repo=repo)
            _wise_automation = WiseAutomation(
                wise_client=wise_client,
                invoice_service=_invoice_services["amzg"],
                contact_service=contact_service,
                telegram=_telegram_notifier,
            )
            logger.info("Wise automation enabled (entity=amzg)")
```

Similarly, for Gmail automation (currently parses Wise transfer emails for HK):

```python
            _gmail_automation = InvoiceAutomation(
                watcher, _invoice_services["amzg"], _telegram_notifier
            )
```

And for the scheduler:

```python
        if settings.scheduler.enabled:
            scheduler = JobScheduler(
                _invoice_services.get("amzg"), settings, _gmail_automation
            )
            scheduler.start()
```

- [ ] **Step 5: Verify main.py imports compile**

Run:
```bash
python -c "import main; print('OK')"
```

Expected: `OK`. No ImportError.

- [ ] **Step 6: Run all existing tests — no regressions**

Run:
```bash
pytest -v
```

Expected: every previously passing test still passes. New tests from Tasks 4, 8, 9 are also green.

- [ ] **Step 7: Commit**

```bash
git add main.py
git commit -m "main.py: per-entity service map (preserves Wise/Gmail HK behaviour)

_invoice_service singleton -> _invoice_services dict keyed by entity slug.
HTTP handlers accept ?entity=... and JSON body entity field. Wise/Gmail
automations explicitly target 'amzg' for backwards compatibility.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 12: Add CLI `db migrate` subcommand

**Files:**
- Modify: `cli.py`

Operators need a way to apply migrations from the CLI. Add a `db migrate` group.

- [ ] **Step 1: Add the migrate command to cli.py**

At the bottom of `cli.py`, add this block before `if __name__ == "__main__":`:

```python
@cli.group()
def db():
    """Goldman database operations."""


@db.command("migrate")
def db_migrate():
    """Apply pending Goldman migrations.

    Uses the admin connection (GOLDMAN_DB_ADMIN_URL). Safe to re-run —
    already-applied migrations are skipped.
    """
    from pathlib import Path
    from goldman_db.connection import admin_conn
    from goldman_db.migrator import apply_pending

    migrations_dir = Path(__file__).resolve().parent / "migrations"
    if not migrations_dir.exists():
        raise click.ClickException(f"No migrations directory at {migrations_dir}")

    with admin_conn() as conn:
        applied = apply_pending(conn, migrations_dir)

    if applied:
        click.echo(f"Applied {len(applied)} migration(s):")
        for name in applied:
            click.echo(f"  ✓ {name}")
    else:
        click.echo("No pending migrations.")
```

- [ ] **Step 2: Verify the command is registered**

Run:
```bash
python cli.py db migrate --help
```

Expected: shows the help text for `db migrate` with no errors.

- [ ] **Step 3: Commit**

```bash
git add cli.py
git commit -m "CLI: add 'db migrate' subcommand

Applies pending SQL migrations via goldman_db.migrator using the admin
connection.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 13: Update `.env.example` and `.env` template

**Files:**
- Modify: `.env.example`

Document the new multi-entity Zoho vars and Goldman DB URLs. Add a deprecation note for the old single-entity vars (but keep them — they may still be in use for the existing service until rename).

- [ ] **Step 1: Append to `.env.example`**

Open `.env.example` and append (after the existing TELEGRAM section):

```bash

# ============================================================================
# Goldman — multi-entity Zoho credentials (preferred for v1)
# ============================================================================
# AMZ Expert Global Limited (Hong Kong parent) — credential key "AMZG"
ZOHO_AMZG_CLIENT_ID=
ZOHO_AMZG_CLIENT_SECRET=
ZOHO_AMZG_REFRESH_TOKEN=
ZOHO_AMZG_ORGANIZATION_ID=
# Optional overrides per entity (defaults match Zoho US data center)
# ZOHO_AMZG_ACCOUNTS_URL=https://accounts.zoho.com
# ZOHO_AMZG_API_BASE_URL=https://www.zohoapis.com/books/v3

# Specific Edge Outsourcing LLC (US subsidiary) — credential key "SEO"
ZOHO_SEO_CLIENT_ID=
ZOHO_SEO_CLIENT_SECRET=
ZOHO_SEO_REFRESH_TOKEN=
ZOHO_SEO_ORGANIZATION_ID=

# ============================================================================
# Goldman Postgres (shared HQ Hub Supabase project, isolated 'goldman' schema)
# ============================================================================
# Admin URL — used by migrations and admin scripts only.
GOLDMAN_DB_ADMIN_URL=
# App URL — runtime queries authenticate as goldman_app role.
GOLDMAN_DB_APP_URL=
```

Also add a comment under the existing ZOHO_CLIENT_ID line:

```bash
# Zoho OAuth2 credentials (DEPRECATED — use ZOHO_AMZG_* instead.
# Kept for the legacy zoho-invoice-agent path; will be removed in Phase 1.)
ZOHO_CLIENT_ID=
```

- [ ] **Step 2: Wire credentials into the seed migration via env**

Open `migrations/0003_seed_entities.sql` and update the `amzg` and `seo` rows so they pick up `zoho_organization_id` from env vars *if available at migrate time*. Since the SQL file is static, we leave the seed columns NULL and provide a follow-up runtime step instead: a one-shot helper added at the bottom of cli.py's db group.

Actually — to keep this strictly SQL-only and idempotent, leave the seed migration as-is (NULLs for `zoho_organization_id`). Provide a `db sync-zoho-org-ids` CLI helper instead.

Add to `cli.py` inside the `db` group:

```python
@db.command("sync-zoho-org-ids")
def db_sync_zoho_org_ids():
    """Backfill goldman.entities.zoho_organization_id from env vars.

    Reads ZOHO_<credkey>_ORGANIZATION_ID for each entity and writes it to
    its row. Idempotent — only updates rows where zoho_organization_id
    is currently NULL or differs from env.
    """
    import os
    from goldman_db.connection import admin_conn

    updates = 0
    with admin_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT slug, zoho_credential_key, zoho_organization_id "
                "FROM goldman.entities"
            )
            rows = cur.fetchall()

        for slug, cred_key, current_org_id in rows:
            if not cred_key:
                continue
            env_org_id = os.getenv(
                f"ZOHO_{cred_key.upper()}_ORGANIZATION_ID", ""
            )
            if env_org_id and env_org_id != current_org_id:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE goldman.entities SET zoho_organization_id = %s "
                        "WHERE slug = %s",
                        (env_org_id, slug),
                    )
                updates += 1
                click.echo(f"  ✓ {slug}: org_id = {env_org_id}")
    if updates:
        click.echo(f"Updated {updates} entit{'y' if updates == 1 else 'ies'}.")
    else:
        click.echo("All entities already in sync.")
```

- [ ] **Step 3: Verify CLI smoke**

Run:
```bash
python cli.py db --help
python cli.py db sync-zoho-org-ids --help
```

Expected: both commands shown with their help text.

- [ ] **Step 4: Commit**

```bash
git add .env.example cli.py
git commit -m "Document multi-entity env vars + add db sync-zoho-org-ids

.env.example now lists ZOHO_AMZG_*, ZOHO_SEO_*, GOLDMAN_DB_*. Old
ZOHO_CLIENT_ID etc. marked deprecated. CLI db group gains sync-zoho-org-ids
to backfill entity rows from env after onboarding.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 14: Migrate the running Supabase project (manual ops step)

**Files:** (no code changes; this is an ops step)

The migrations exist. Apply them to the shared HQ Hub Supabase project (`tjxngrplgiqicdorsjzr`).

- [ ] **Step 1: Locate the admin connection string**

Open https://supabase.com/dashboard/project/tjxngrplgiqicdorsjzr/settings/database → "Connection string" → "URI" → choose "Use connection pooling" and copy the URL with the service-role password. Save it as `GOLDMAN_DB_ADMIN_URL` in your local `.env` file (the value with `?sslmode=require` appended).

- [ ] **Step 2: Run the migrator**

```bash
cd ~/Desktop/Obsidian/Projects/zoho-invoice-agent
python cli.py db migrate
```

Expected output:
```
Applied 3 migration(s):
  ✓ 0001_goldman_schema.sql
  ✓ 0002_entities.sql
  ✓ 0003_seed_entities.sql
```

- [ ] **Step 3: Verify the schema landed**

Run:
```bash
python -c "
import os, psycopg
url = os.environ['GOLDMAN_DB_ADMIN_URL']
with psycopg.connect(url) as conn, conn.cursor() as cur:
    cur.execute(\"SELECT slug, legal_name, jurisdiction FROM goldman.entities ORDER BY slug\")
    for row in cur.fetchall(): print(row)
"
```

Expected: prints two rows:
```
('amzg', 'AMZ Expert Global Limited', 'HK')
('seo', 'Specific Edge Outsourcing LLC', 'US')
```

- [ ] **Step 4: Set the goldman_app_login password and capture the app URL**

In the Supabase SQL editor, run:
```sql
ALTER ROLE goldman_app_login WITH PASSWORD 'GENERATE_A_STRONG_PASSWORD_HERE';
```

Then build the app URL: take the admin URL and replace `postgres` (the user) with `goldman_app_login` and the password with the one you just set. Save it as `GOLDMAN_DB_APP_URL` in `.env`.

- [ ] **Step 5: Verify app-role isolation**

Run:
```bash
python -c "
import os, psycopg
url = os.environ['GOLDMAN_DB_APP_URL']
with psycopg.connect(url) as conn, conn.cursor() as cur:
    # Should succeed
    cur.execute('SELECT count(*) FROM goldman.entities')
    print('goldman.entities count:', cur.fetchone()[0])
    # Should fail
    try:
        cur.execute('SELECT count(*) FROM public.clients')
        print('UNEXPECTED — public access leaked:', cur.fetchone()[0])
    except psycopg.errors.InsufficientPrivilege as e:
        print('isolation OK — public denied')
"
```

Expected:
```
goldman.entities count: 2
isolation OK — public denied
```

If the second query *succeeds*, the isolation defense failed — STOP and investigate before proceeding.

- [ ] **Step 6: Sync Zoho org IDs from env**

```bash
python cli.py db sync-zoho-org-ids
```

Expected: prints "Updated 1 entity" or "Updated 2 entities" depending on which entity creds you have set.

- [ ] **Step 7: Document the credentials locally**

Update your local `.env` with both URLs. Do NOT commit `.env` — it's already in `.gitignore`. The env vars get set on Render in Task 16.

---

## Task 15: End-to-end smoke test against both Zoho orgs

**Files:** (no code changes)

Confirm the factory routes correctly to each Zoho org without smashing them together.

- [ ] **Step 1: List invoices for amzg**

```bash
python cli.py list --entity amzg --page 1
```

Expected: prints recent AMZ Expert Global invoices (or "No invoices found" if the org is empty — both are valid). NO error.

- [ ] **Step 2: List invoices for seo**

```bash
python cli.py list --entity seo --page 1
```

Expected: prints Specific Edge Outsourcing invoices (or "No invoices found"). Critically — these should be DIFFERENT invoices than step 1. If they're identical, the factory isn't routing to the right org.

- [ ] **Step 3: Confirm error path — unknown entity**

```bash
python cli.py list --entity nope
```

Expected: exits with an error mentioning `nope`. No silent fallback to amzg.

- [ ] **Step 4: Run full test suite**

```bash
pytest -v
```

Expected: all tests pass — both new Goldman tests and the existing zoho-invoice-agent tests. Note any flaky tests.

- [ ] **Step 5: Commit (if any local fixes were needed)**

If steps 1-4 surface bugs, fix them in the relevant module and commit. If everything is green, no commit needed for this task.

---

## Task 16: Rename — repo, GitHub, Render

**Files:**
- Modify: `render.yaml`

Now and only now do we rename. All code is verified working with the old paths.

- [ ] **Step 1: Update render.yaml**

In `render.yaml`, change:

```yaml
services:
  - type: web
    name: zoho-invoice-agent
    runtime: python
    repo: https://github.com/Liranham/zoho-invoice-agent
```

to:

```yaml
services:
  - type: web
    name: goldman
    runtime: python
    repo: https://github.com/Liranham/goldman
```

Commit on the OLD repo first:
```bash
git add render.yaml
git commit -m "render.yaml: rename service to goldman, update repo URL

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
git push origin main
```

- [ ] **Step 2: Rename the GitHub repository**

Run:
```bash
gh repo rename goldman --repo Liranham/zoho-invoice-agent
```

Expected: `✓ Renamed repository to Liranham/goldman`. GitHub redirects the old URL automatically.

- [ ] **Step 3: Update the local git remote**

```bash
git remote set-url origin git@github.com:Liranham/goldman.git
git remote -v
```

Expected: `origin  git@github.com:Liranham/goldman.git (fetch/push)`.

- [ ] **Step 4: Rename the working directory**

```bash
cd ~/Desktop/Obsidian/Projects
mv zoho-invoice-agent goldman
cd goldman
pwd
```

Expected: `/Users/hamburg/Desktop/Obsidian/Projects/goldman`.

- [ ] **Step 5: Rename the Render service**

Render's API supports patching the service name. Run (substituting your Render API key):

```bash
# 1. Look up the service ID
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services?name=zoho-invoice-agent&limit=1" \
  | python -c "import sys,json; data=json.load(sys.stdin); print(data[0]['service']['id'])"
```

Then with the returned `SERVICE_ID`:

```bash
SERVICE_ID=<paste-id-here>
curl -s -X PATCH \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"goldman","repo":"https://github.com/Liranham/goldman"}' \
  "https://api.render.com/v1/services/$SERVICE_ID"
```

Expected: JSON response with `"name": "goldman"` and the new URL `https://goldman.onrender.com`.

- [ ] **Step 6: Set Render env vars for both entities**

Per Liran's CLAUDE.md gotcha: env vars in service create are silently ignored. Use PUT /env-vars explicitly. For each new env var (`ZOHO_AMZG_*`, `ZOHO_SEO_*`, `GOLDMAN_DB_APP_URL`, plus the Telegram bot token from `@BotFather` when received), call:

```bash
curl -s -X PUT \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '[
    {"key":"ZOHO_AMZG_CLIENT_ID","value":"..."},
    {"key":"ZOHO_AMZG_CLIENT_SECRET","value":"..."},
    {"key":"ZOHO_AMZG_REFRESH_TOKEN","value":"..."},
    {"key":"ZOHO_AMZG_ORGANIZATION_ID","value":"..."},
    {"key":"ZOHO_SEO_CLIENT_ID","value":"..."},
    {"key":"ZOHO_SEO_CLIENT_SECRET","value":"..."},
    {"key":"ZOHO_SEO_REFRESH_TOKEN","value":"..."},
    {"key":"ZOHO_SEO_ORGANIZATION_ID","value":"..."},
    {"key":"GOLDMAN_DB_APP_URL","value":"..."}
  ]' \
  "https://api.render.com/v1/services/$SERVICE_ID/env-vars"
```

Use the actual values from your local `.env`. Existing env vars (TELEGRAM_*, WISE_*, etc.) are preserved by Render — this PUT only updates / inserts.

- [ ] **Step 7: Trigger a deploy and confirm health**

```bash
curl -s -X POST \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/$SERVICE_ID/deploys"

# Wait ~60s, then:
curl -s https://goldman.onrender.com/health
```

Expected: `{"status":"ok","service":"zoho-invoice-agent"}` — note the `service` field still reads `zoho-invoice-agent` because that's hardcoded in the existing `main.py` `_handle_health` (around line 36). That's fine for v1 — Phase 1 will update it.

Actually let's fix that now since it's a one-line change:

- [ ] **Step 8: Update health response service name**

In `main.py`, change:

```python
        if self.path in ("/", "/health"):
            self._json_response(200, {"status": "ok", "service": "zoho-invoice-agent"})
```

to:

```python
        if self.path in ("/", "/health"):
            self._json_response(200, {"status": "ok", "service": "goldman"})
```

Commit:
```bash
git add main.py
git commit -m "Health endpoint reports service: goldman

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
git push origin main
```

- [ ] **Step 9: Wait for redeploy + final health check**

```bash
sleep 90
curl -s https://goldman.onrender.com/health
```

Expected: `{"status":"ok","service":"goldman"}`.

- [ ] **Step 10: Confirm running entity routing in production**

```bash
curl -s "https://goldman.onrender.com/invoices?entity=amzg" | head -c 200
echo
curl -s "https://goldman.onrender.com/invoices?entity=seo" | head -c 200
```

Expected: two different JSON responses (or both with `"invoices": []` — valid if both orgs are empty). NOT the same response.

---

## Task 17: Final regression sweep + Phase 0 completion commit

**Files:** (no code changes; checkpoint)

- [ ] **Step 1: Run all tests one last time**

```bash
cd ~/Desktop/Obsidian/Projects/goldman
pytest -v
```

Expected: every test green.

- [ ] **Step 2: Confirm git state is clean**

```bash
git status
git log --oneline -10
```

Expected: clean working tree, recent commits reflect Tasks 1–16.

- [ ] **Step 3: Final smoke against both entities**

```bash
python cli.py list --entity amzg --page 1
python cli.py list --entity seo --page 1
python cli.py customers --entity amzg | head -5
python cli.py customers --entity seo | head -5
```

Expected: each prints data scoped to the correct entity. The customer lists differ.

- [ ] **Step 4: Tag the Phase 0 completion**

```bash
git tag -a phase-0-complete -m "Goldman Phase 0 complete — foundation + multi-entity Zoho factory"
git push origin phase-0-complete
```

- [ ] **Step 5: Update task tracking**

Mark Phase 0 done in the project's broader plan, then proceed to writing Phase 1.

---

## Spec coverage cross-check

| Spec section | Covered by task(s) |
|---|---|
| §3 — Architecture (Python pkg + front doors) | Tasks 9, 10, 11 (factory + CLI + main routing) |
| §4 — Repo strategy (rename + evolve) | Tasks 14, 16 (rename last) |
| §5.1 — Entities table | Tasks 6, 7 (schema + seed) |
| §5.3 — Multi-Zoho factory | Task 9 (factory) + Tasks 10, 11 (wiring) |
| §6.5 — Schema isolation defenses | Task 5 (REVOKE + role) + Task 14 step 5 (verify isolation) |
| §10 — Phase 0 deliverable | All tasks |
| §11 — Defaults (env conventions) | Task 13 (.env.example) |

All Phase 0 spec requirements have at least one implementing task.

---

## What's intentionally NOT in this plan

- `tax_registrations`, `clients`, `vendors`, `bank_accounts` tables — Phase 1.
- `goldman_conversation_turns`, `goldman_facts`, `goldman_documents` tables — Phase 2.
- Onboarding brain-dump flow — Phase 1.
- Any change to Wise/Gmail intake logic beyond routing to `amzg` — Phase 3.
- Telegram bot for Goldman (separate from Bob) — Phase 4.
- Claude Code plugin — Phase 5.

Each gets its own plan written when the prior phase completes.
