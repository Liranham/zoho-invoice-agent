# Goldman Phase 1 — Company Brain v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Goldman learns the company. Four new entity-scoped tables (tax_registrations, clients, vendors, bank_accounts) plus a minimal goldman_facts table; a conversational brain-dump onboarding flow that converts free text into structured rows via Claude; per-entity Zoho contact sync into clients + vendors; a composable `goldman who` command that prints the company tree end-to-end.

**Architecture:** Continue the Phase 0 pattern — one Python package per concern (`goldman/`, `goldman_db/`), SQL migrations under `migrations/`, TDD per repository, CLI commands as the user surface. New concern: `goldman/llm.py` wraps the Anthropic SDK for the onboarding extraction; `goldman/onboarding/` holds the extract/coverage/gap-fill flow; `goldman/who.py` is a composable view function reusable from Telegram and the Claude Code plugin later. Free-floating facts land in a minimal `goldman.facts` table now — Phase 2 will ALTER it to add the embedding + capabilities the memory system needs (additive, no data migration).

**Tech Stack:** Python 3.9+, `anthropic>=0.40` (new dependency), existing `psycopg`, `requests`, `click`, `pytest`, `python-dotenv`. Claude model: `claude-sonnet-4-6` for extraction (accurate, fast, cheap enough for one-time onboarding + light gap-fill).

---

## File Map

**Create:**
- `migrations/0004_tax_registrations.sql` — `goldman.tax_registrations` table.
- `migrations/0005_clients.sql` — `goldman.clients` table.
- `migrations/0006_vendors.sql` — `goldman.vendors` table.
- `migrations/0007_bank_accounts.sql` — `goldman.bank_accounts` table.
- `migrations/0008_facts.sql` — minimal `goldman.facts` table (Phase 2 will ALTER).
- `migrations/0009_entities_metadata.sql` — no-op safety migration that confirms `goldman.entities` already has the metadata columns we'll write to.
- `goldman_db/tax_registrations.py` — `TaxRegistration` dataclass + `TaxRegistrationRepository`.
- `goldman_db/clients.py` — `Client` dataclass + `ClientRepository`.
- `goldman_db/vendors.py` — `Vendor` dataclass + `VendorRepository`.
- `goldman_db/bank_accounts.py` — `BankAccount` dataclass + `BankAccountRepository`.
- `goldman_db/facts.py` — `Fact` dataclass + `FactRepository`.
- `goldman/llm.py` — thin Anthropic SDK wrapper (`GoldmanLLM` with `extract_with_tool()`).
- `goldman/onboarding/__init__.py` — package marker.
- `goldman/onboarding/extract.py` — extraction prompt + tool schema + result parser.
- `goldman/onboarding/writer.py` — writes extracted data into the 5 tables + entities metadata.
- `goldman/onboarding/coverage.py` — coverage check (what mandatory facts are missing per entity).
- `goldman/onboarding/gap_fill.py` — interactive gap-question loop.
- `goldman/onboarding/flow.py` — top-level orchestrator (`run_onboarding(entity_slug)`).
- `goldman/sync/__init__.py` — package marker.
- `goldman/sync/zoho_contacts.py` — sync Zoho contacts into `clients` + `vendors`.
- `goldman/who.py` — `who_view(entity_slug=None)` composable aggregator + plain-text renderer.
- `tests/test_goldman_tax_registrations_repo.py`
- `tests/test_goldman_clients_repo.py`
- `tests/test_goldman_vendors_repo.py`
- `tests/test_goldman_bank_accounts_repo.py`
- `tests/test_goldman_facts_repo.py`
- `tests/test_goldman_llm.py`
- `tests/test_goldman_onboarding_extract.py`
- `tests/test_goldman_onboarding_writer.py`
- `tests/test_goldman_onboarding_coverage.py`
- `tests/test_goldman_sync_zoho_contacts.py`
- `tests/test_goldman_who.py`

**Modify:**
- `requirements.txt` — add `anthropic>=0.40`.
- `goldman_db/entities.py` — add `update_metadata(slug, **fields)` method.
- `cli.py` — add `onboard`, `sync` (group with `zoho-contacts` subcommand), `who` commands.
- `.env.example` — add `ANTHROPIC_API_KEY=` (already exists in Liran's env for HQ Hub; mirror it).

---

## Task 1: Add Anthropic SDK dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add anthropic to requirements**

Append to `requirements.txt`:
```
anthropic>=0.40.0
```

- [ ] **Step 2: Install locally**

Run:
```bash
python3 -m pip install --user -r requirements.txt 2>&1 | tail -5
```

Expected: pip installs `anthropic` and its dependencies (httpx, pydantic, etc.). No errors.

- [ ] **Step 3: Verify import**

Run:
```bash
python3 -c "import anthropic; print('anthropic', anthropic.__version__)"
```

Expected: prints version >= 0.40, e.g. `anthropic 0.45.2`.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "Add Anthropic SDK for Goldman LLM access

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Migration 0004 — tax_registrations

**Files:**
- Create: `migrations/0004_tax_registrations.sql`

Append-only design: `effective_to` represents true business state (deregistration); `supersedes_id` represents corrections. Current truth = leaf row in supersedes chain.

- [ ] **Step 1: Write the SQL**

Create `migrations/0004_tax_registrations.sql`:

```sql
-- Goldman tax_registrations: append-only ledger of tax registrations per entity.
-- Per spec §5.2 — corrections via supersedes_id, never UPDATE.

CREATE TABLE IF NOT EXISTS goldman.tax_registrations (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id           UUID         NOT NULL REFERENCES goldman.entities(id),
    tax_type            TEXT         NOT NULL CHECK (tax_type IN (
        'vat', 'sales_tax', 'profits_tax', 'income_tax',
        'withholding_tax', 'payroll_tax', 'other'
    )),
    jurisdiction        TEXT         NOT NULL,   -- e.g. 'HK', 'GB', 'US-TX'
    registration_number TEXT,                    -- e.g. 'GB123456789'
    effective_from      DATE,
    effective_to        DATE,                    -- NULL = still active
    filing_cadence      TEXT         CHECK (filing_cadence IN (
        'monthly', 'quarterly', 'annual', 'irregular'
    ) OR filing_cadence IS NULL),
    notes               TEXT,
    supersedes_id       UUID         REFERENCES goldman.tax_registrations(id),
    source              TEXT         NOT NULL DEFAULT 'user_explicit' CHECK (source IN (
        'user_explicit', 'extracted', 'data_derived'
    )),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_goldman_tax_reg_entity
    ON goldman.tax_registrations(entity_id);
CREATE INDEX IF NOT EXISTS idx_goldman_tax_reg_supersedes
    ON goldman.tax_registrations(supersedes_id)
    WHERE supersedes_id IS NOT NULL;

-- "Live" view: rows that are not superseded by anything.
CREATE OR REPLACE VIEW goldman.tax_registrations_live AS
SELECT tr.*
FROM goldman.tax_registrations tr
WHERE NOT EXISTS (
    SELECT 1 FROM goldman.tax_registrations tr2
    WHERE tr2.supersedes_id = tr.id
);

COMMENT ON TABLE goldman.tax_registrations IS
    'Append-only. Corrections create new rows via supersedes_id. Never UPDATE.';
```

- [ ] **Step 2: Verify**

```bash
python3 -c "
from pathlib import Path
sql = Path('migrations/0004_tax_registrations.sql').read_text()
assert 'CREATE TABLE IF NOT EXISTS goldman.tax_registrations' in sql
assert 'supersedes_id' in sql
assert 'goldman.tax_registrations_live' in sql
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add migrations/0004_tax_registrations.sql
git commit -m "Add migration 0004: goldman.tax_registrations (append-only)

Includes goldman.tax_registrations_live view for current-state queries.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Migration 0005 — clients

**Files:**
- Create: `migrations/0005_clients.sql`

- [ ] **Step 1: Write the SQL**

Create `migrations/0005_clients.sql`:

```sql
-- Goldman clients: synced from each entity's Zoho contacts, enriched with tier.
-- Per spec §5.2.

CREATE TABLE IF NOT EXISTS goldman.clients (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id         UUID         NOT NULL REFERENCES goldman.entities(id),
    zoho_contact_id   TEXT         NOT NULL,
    contact_name      TEXT         NOT NULL,
    company_name      TEXT,
    primary_email     TEXT,
    tier              TEXT         CHECK (tier IN ('a', 'b', 'c') OR tier IS NULL),
    primary_contact   TEXT,
    notes             TEXT,
    last_synced_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (entity_id, zoho_contact_id)
);

CREATE INDEX IF NOT EXISTS idx_goldman_clients_entity
    ON goldman.clients(entity_id);
CREATE INDEX IF NOT EXISTS idx_goldman_clients_zoho
    ON goldman.clients(entity_id, zoho_contact_id);

DROP TRIGGER IF EXISTS trg_clients_updated_at ON goldman.clients;
CREATE TRIGGER trg_clients_updated_at
    BEFORE UPDATE ON goldman.clients
    FOR EACH ROW
    EXECUTE FUNCTION goldman.set_updated_at();
```

- [ ] **Step 2: Verify + Commit**

```bash
python3 -c "
from pathlib import Path
sql = Path('migrations/0005_clients.sql').read_text()
assert 'CREATE TABLE IF NOT EXISTS goldman.clients' in sql
assert 'UNIQUE (entity_id, zoho_contact_id)' in sql
print('OK')
" && git add migrations/0005_clients.sql && git commit -m "Add migration 0005: goldman.clients (Zoho-synced + entity-scoped)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: `OK` then commit hash.

---

## Task 4: Migration 0006 — vendors

**Files:**
- Create: `migrations/0006_vendors.sql`

- [ ] **Step 1: Write the SQL**

Create `migrations/0006_vendors.sql`:

```sql
-- Goldman vendors: from Zoho contacts + recurring-expense detection.
-- Per spec §5.2 — supports trust-gate decisions in Phase 3.

CREATE TABLE IF NOT EXISTS goldman.vendors (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id         UUID         NOT NULL REFERENCES goldman.entities(id),
    zoho_contact_id   TEXT,                       -- nullable; vendor may not be in Zoho yet
    vendor_name       TEXT         NOT NULL,
    email_domain      TEXT,                       -- for fuzzy match on inbound bills
    category          TEXT         CHECK (category IN (
        'hosting', 'factory', 'shipping', 'software',
        'professional_services', 'utilities', 'other'
    ) OR category IS NULL),
    typical_amount    NUMERIC(14, 2),
    typical_currency  TEXT,
    typical_cadence   TEXT         CHECK (typical_cadence IN (
        'weekly', 'monthly', 'quarterly', 'annual', 'irregular'
    ) OR typical_cadence IS NULL),
    always_confirm    BOOLEAN      NOT NULL DEFAULT FALSE,
    last_seen_at      TIMESTAMPTZ,
    seen_count        INTEGER      NOT NULL DEFAULT 0,
    notes             TEXT,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (entity_id, vendor_name)
);

CREATE INDEX IF NOT EXISTS idx_goldman_vendors_entity
    ON goldman.vendors(entity_id);
CREATE INDEX IF NOT EXISTS idx_goldman_vendors_zoho
    ON goldman.vendors(entity_id, zoho_contact_id)
    WHERE zoho_contact_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_goldman_vendors_domain
    ON goldman.vendors(email_domain)
    WHERE email_domain IS NOT NULL;

DROP TRIGGER IF EXISTS trg_vendors_updated_at ON goldman.vendors;
CREATE TRIGGER trg_vendors_updated_at
    BEFORE UPDATE ON goldman.vendors
    FOR EACH ROW
    EXECUTE FUNCTION goldman.set_updated_at();
```

- [ ] **Step 2: Verify + Commit**

```bash
python3 -c "
from pathlib import Path
sql = Path('migrations/0006_vendors.sql').read_text()
assert 'CREATE TABLE IF NOT EXISTS goldman.vendors' in sql
assert 'always_confirm' in sql
assert 'UNIQUE (entity_id, vendor_name)' in sql
print('OK')
" && git add migrations/0006_vendors.sql && git commit -m "Add migration 0006: goldman.vendors (with trust-gate fields)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: `OK` then commit.

---

## Task 5: Migration 0007 — bank_accounts

**Files:**
- Create: `migrations/0007_bank_accounts.sql`

- [ ] **Step 1: Write the SQL**

Create `migrations/0007_bank_accounts.sql`:

```sql
-- Goldman bank_accounts: bank + fintech accounts per entity.
-- Per spec §5.2 — manual entry in v1; live Wise sync deferred to Phase 6.

CREATE TABLE IF NOT EXISTS goldman.bank_accounts (
    id                 UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id          UUID         NOT NULL REFERENCES goldman.entities(id),
    provider           TEXT         NOT NULL,           -- 'Wise', 'HSBC', 'Chase', etc.
    account_label      TEXT         NOT NULL,           -- 'Wise USD Operating'
    currency           TEXT         NOT NULL,
    account_identifier TEXT,                            -- masked, e.g. '****1234'
    last_balance       NUMERIC(14, 2),
    last_balance_at    TIMESTAMPTZ,
    notes              TEXT,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (entity_id, account_label)
);

CREATE INDEX IF NOT EXISTS idx_goldman_bank_entity
    ON goldman.bank_accounts(entity_id);

DROP TRIGGER IF EXISTS trg_bank_accounts_updated_at ON goldman.bank_accounts;
CREATE TRIGGER trg_bank_accounts_updated_at
    BEFORE UPDATE ON goldman.bank_accounts
    FOR EACH ROW
    EXECUTE FUNCTION goldman.set_updated_at();
```

- [ ] **Step 2: Verify + Commit**

```bash
python3 -c "
from pathlib import Path
sql = Path('migrations/0007_bank_accounts.sql').read_text()
assert 'CREATE TABLE IF NOT EXISTS goldman.bank_accounts' in sql
assert 'last_balance' in sql
print('OK')
" && git add migrations/0007_bank_accounts.sql && git commit -m "Add migration 0007: goldman.bank_accounts (manual entry, Phase 6 live sync later)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Migration 0008 — minimal goldman.facts (Phase 2 will extend)

**Files:**
- Create: `migrations/0008_facts.sql`

Append-only ledger of free-floating facts. Phase 2 adds `embedding VECTOR(1536)`, `conflict_with UUID[]`, and search RPCs via additive ALTER migrations.

- [ ] **Step 1: Write the SQL**

Create `migrations/0008_facts.sql`:

```sql
-- Goldman facts: append-only structured facts.
-- Per spec §6.1 — corrections via supersedes_id, never UPDATE.
-- Phase 2 will ALTER to add: embedding column, conflict_with[], capabilities table.

CREATE TABLE IF NOT EXISTS goldman.facts (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id     UUID         REFERENCES goldman.entities(id),   -- nullable for cross-entity
    kind          TEXT         NOT NULL CHECK (kind IN (
        'target', 'preference', 'constraint',
        'commitment', 'event', 'decision', 'note'
    )),
    fact          TEXT         NOT NULL,
    content_hash  TEXT         NOT NULL,                          -- sha256 of normalized fact
    supersedes_id UUID         REFERENCES goldman.facts(id),
    source        TEXT         NOT NULL DEFAULT 'user_explicit' CHECK (source IN (
        'user_explicit', 'extracted', 'data_derived'
    )),
    seen_count    INTEGER      NOT NULL DEFAULT 1,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (entity_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_goldman_facts_entity
    ON goldman.facts(entity_id);
CREATE INDEX IF NOT EXISTS idx_goldman_facts_kind
    ON goldman.facts(kind);
CREATE INDEX IF NOT EXISTS idx_goldman_facts_supersedes
    ON goldman.facts(supersedes_id)
    WHERE supersedes_id IS NOT NULL;

-- "Live" view: leaf rows of supersedes chains.
CREATE OR REPLACE VIEW goldman.facts_live AS
SELECT f.*
FROM goldman.facts f
WHERE NOT EXISTS (
    SELECT 1 FROM goldman.facts f2 WHERE f2.supersedes_id = f.id
);

COMMENT ON TABLE goldman.facts IS
    'Append-only. Phase 2 adds embedding + conflict detection. Never UPDATE.';
```

- [ ] **Step 2: Verify + Commit**

```bash
python3 -c "
from pathlib import Path
sql = Path('migrations/0008_facts.sql').read_text()
assert 'CREATE TABLE IF NOT EXISTS goldman.facts' in sql
assert 'goldman.facts_live' in sql
assert 'content_hash' in sql
print('OK')
" && git add migrations/0008_facts.sql && git commit -m "Add migration 0008: minimal goldman.facts (Phase 2 extends)

Append-only with supersedes_id. Phase 2 will ALTER to add embedding,
conflict detection, capabilities registry.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Apply migrations 0004-0008 to live Supabase

**Files:** (no code changes — operational verification)

- [ ] **Step 1: Run the migrator**

```bash
cd ~/Desktop/Obsidian/Projects/zoho-invoice-agent
python3 cli.py db migrate
```

Expected output:
```
Applied 5 migration(s):
  ✓ 0004_tax_registrations.sql
  ✓ 0005_clients.sql
  ✓ 0006_vendors.sql
  ✓ 0007_bank_accounts.sql
  ✓ 0008_facts.sql
```

- [ ] **Step 2: Verify the new tables exist**

```bash
python3 -c "
import os, psycopg
from dotenv import load_dotenv
load_dotenv()
url = os.environ['GOLDMAN_DB_ADMIN_URL']
with psycopg.connect(url) as conn, conn.cursor() as cur:
    cur.execute(\"\"\"
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'goldman'
        ORDER BY table_name
    \"\"\")
    for row in cur.fetchall(): print(' ', row[0])
"
```

Expected (alphabetical order):
```
  bank_accounts
  clients
  entities
  facts
  migrations
  tax_registrations
```

- [ ] **Step 3: Verify goldman_app_login can read all new tables**

```bash
python3 -c "
import os, psycopg
from dotenv import load_dotenv
load_dotenv()
url = os.environ['GOLDMAN_DB_APP_URL']
with psycopg.connect(url) as conn, conn.cursor() as cur:
    for tbl in ['tax_registrations', 'clients', 'vendors', 'bank_accounts', 'facts']:
        cur.execute(f'SELECT count(*) FROM goldman.{tbl}')
        print(f'  goldman.{tbl}: {cur.fetchone()[0]} rows')
"
```

Expected: all five tables print `0 rows`. NO permission errors.

- [ ] **Step 4: Verify migrator state**

```bash
python3 -c "
import os, psycopg
from dotenv import load_dotenv
load_dotenv()
url = os.environ['GOLDMAN_DB_ADMIN_URL']
with psycopg.connect(url) as conn, conn.cursor() as cur:
    cur.execute('SELECT filename FROM goldman.migrations ORDER BY filename')
    for row in cur.fetchall(): print(' ', row[0])
"
```

Expected: prints all 8 migration filenames (0001 through 0008).

---

## Task 8: TaxRegistrationRepository (TDD)

**Files:**
- Create: `goldman_db/tax_registrations.py`
- Test: `tests/test_goldman_tax_registrations_repo.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_tax_registrations_repo.py`:

```python
"""Tests for TaxRegistrationRepository."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from goldman_db.tax_registrations import TaxRegistration, TaxRegistrationRepository


def test_insert_returns_new_row():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = TaxRegistrationRepository(conn)
    entity_id = uuid4()
    returned_id = repo.insert(
        entity_id=entity_id,
        tax_type="vat",
        jurisdiction="GB",
        registration_number="GB123456789",
        effective_from=date(2024, 3, 1),
        filing_cadence="quarterly",
        source="user_explicit",
    )

    assert returned_id == new_id
    # Verify INSERT was called
    insert_call = cur.execute.call_args
    assert "INSERT INTO goldman.tax_registrations" in str(insert_call)


def test_list_live_for_entity():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    entity_id = uuid4()
    row_id = uuid4()
    cur.fetchall.return_value = [
        (row_id, entity_id, "vat", "GB", "GB123456789",
         date(2024, 3, 1), None, "quarterly", "test notes",
         None, "user_explicit"),
    ]

    repo = TaxRegistrationRepository(conn)
    rows = repo.list_live(entity_id)

    assert len(rows) == 1
    assert rows[0].tax_type == "vat"
    assert rows[0].jurisdiction == "GB"
    assert rows[0].registration_number == "GB123456789"
    # Verify the query targeted the live view
    select_call = cur.execute.call_args
    assert "tax_registrations_live" in str(select_call)


def test_supersede_inserts_new_row_with_supersedes_id():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = TaxRegistrationRepository(conn)
    prior_id = uuid4()
    entity_id = uuid4()

    returned_id = repo.supersede(
        prior_id=prior_id,
        entity_id=entity_id,
        tax_type="vat",
        jurisdiction="GB",
        registration_number="GB123456789",
        effective_from=date(2024, 3, 1),
        effective_to=date(2026, 9, 15),
        filing_cadence="quarterly",
        source="user_explicit",
    )

    assert returned_id == new_id
    insert_call_args = cur.execute.call_args
    assert "INSERT INTO goldman.tax_registrations" in str(insert_call_args)
    # supersedes_id must be passed as a parameter
    params = insert_call_args[0][1]
    assert prior_id in params
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_tax_registrations_repo.py -v 2>&1 | tail -8
```

Expected: `ModuleNotFoundError: No module named 'goldman_db.tax_registrations'`.

- [ ] **Step 3: Implement the repository**

Create `goldman_db/tax_registrations.py`:

```python
"""Repository for goldman.tax_registrations (append-only)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class TaxRegistration:
    id: UUID
    entity_id: UUID
    tax_type: str
    jurisdiction: str
    registration_number: Optional[str]
    effective_from: Optional[date]
    effective_to: Optional[date]
    filing_cadence: Optional[str]
    notes: Optional[str]
    supersedes_id: Optional[UUID]
    source: str


_COLS = """
    id, entity_id, tax_type, jurisdiction, registration_number,
    effective_from, effective_to, filing_cadence, notes,
    supersedes_id, source
"""


def _row_to_obj(row) -> TaxRegistration:
    return TaxRegistration(
        id=row[0], entity_id=row[1], tax_type=row[2],
        jurisdiction=row[3], registration_number=row[4],
        effective_from=row[5], effective_to=row[6],
        filing_cadence=row[7], notes=row[8],
        supersedes_id=row[9], source=row[10],
    )


class TaxRegistrationRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def insert(
        self,
        *,
        entity_id: UUID,
        tax_type: str,
        jurisdiction: str,
        registration_number: Optional[str] = None,
        effective_from: Optional[date] = None,
        effective_to: Optional[date] = None,
        filing_cadence: Optional[str] = None,
        notes: Optional[str] = None,
        source: str = "user_explicit",
    ) -> UUID:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.tax_registrations
                    (entity_id, tax_type, jurisdiction, registration_number,
                     effective_from, effective_to, filing_cadence, notes, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (entity_id, tax_type, jurisdiction, registration_number,
                 effective_from, effective_to, filing_cadence, notes, source),
            )
            return cur.fetchone()[0]

    def supersede(
        self,
        *,
        prior_id: UUID,
        entity_id: UUID,
        tax_type: str,
        jurisdiction: str,
        registration_number: Optional[str] = None,
        effective_from: Optional[date] = None,
        effective_to: Optional[date] = None,
        filing_cadence: Optional[str] = None,
        notes: Optional[str] = None,
        source: str = "user_explicit",
    ) -> UUID:
        """Insert a corrected row that supersedes a prior one. Original preserved."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.tax_registrations
                    (entity_id, tax_type, jurisdiction, registration_number,
                     effective_from, effective_to, filing_cadence, notes,
                     supersedes_id, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (entity_id, tax_type, jurisdiction, registration_number,
                 effective_from, effective_to, filing_cadence, notes,
                 prior_id, source),
            )
            return cur.fetchone()[0]

    def list_live(self, entity_id: UUID) -> list[TaxRegistration]:
        """Return the leaf rows of supersedes chains for this entity."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS}
                FROM goldman.tax_registrations_live
                WHERE entity_id = %s
                ORDER BY created_at
                """,
                (entity_id,),
            )
            return [_row_to_obj(r) for r in cur.fetchall()]
```

- [ ] **Step 4: Run tests — should pass**

```bash
python3 -m pytest tests/test_goldman_tax_registrations_repo.py -v 2>&1 | tail -6
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add goldman_db/tax_registrations.py tests/test_goldman_tax_registrations_repo.py
git commit -m "Add TaxRegistrationRepository (insert/supersede/list_live)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: ClientRepository (TDD)

**Files:**
- Create: `goldman_db/clients.py`
- Test: `tests/test_goldman_clients_repo.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_clients_repo.py`:

```python
"""Tests for ClientRepository."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.clients import Client, ClientRepository


def test_upsert_by_zoho_id_inserts_new():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = ClientRepository(conn)
    entity_id = uuid4()
    returned_id = repo.upsert_by_zoho_id(
        entity_id=entity_id,
        zoho_contact_id="zoho_c_123",
        contact_name="Acme Corp",
        company_name="Acme",
        primary_email="ops@acme.com",
    )

    assert returned_id == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.clients" in sql
    assert "ON CONFLICT" in sql


def test_list_by_entity_returns_clients():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cid = uuid4()
    eid = uuid4()
    cur.fetchall.return_value = [
        (cid, eid, "zoho_c_1", "Acme", "Acme Inc",
         "ops@acme.com", "a", None, None),
    ]

    repo = ClientRepository(conn)
    clients = repo.list_by_entity(eid)

    assert len(clients) == 1
    assert clients[0].contact_name == "Acme"
    assert clients[0].tier == "a"


def test_set_tier_updates_row():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = ClientRepository(conn)
    cid = uuid4()

    repo.set_tier(cid, "b")

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.clients" in sql
    assert "tier" in sql
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_clients_repo.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman_db/clients.py`:

```python
"""Repository for goldman.clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class Client:
    id: UUID
    entity_id: UUID
    zoho_contact_id: str
    contact_name: str
    company_name: Optional[str]
    primary_email: Optional[str]
    tier: Optional[str]
    primary_contact: Optional[str]
    notes: Optional[str]


_COLS = """
    id, entity_id, zoho_contact_id, contact_name, company_name,
    primary_email, tier, primary_contact, notes
"""


def _row(r) -> Client:
    return Client(
        id=r[0], entity_id=r[1], zoho_contact_id=r[2],
        contact_name=r[3], company_name=r[4], primary_email=r[5],
        tier=r[6], primary_contact=r[7], notes=r[8],
    )


class ClientRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def upsert_by_zoho_id(
        self,
        *,
        entity_id: UUID,
        zoho_contact_id: str,
        contact_name: str,
        company_name: Optional[str] = None,
        primary_email: Optional[str] = None,
    ) -> UUID:
        """Insert or update on (entity_id, zoho_contact_id). Returns the row id."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.clients
                    (entity_id, zoho_contact_id, contact_name,
                     company_name, primary_email, last_synced_at)
                VALUES (%s, %s, %s, %s, %s, now())
                ON CONFLICT (entity_id, zoho_contact_id) DO UPDATE
                    SET contact_name = EXCLUDED.contact_name,
                        company_name = EXCLUDED.company_name,
                        primary_email = EXCLUDED.primary_email,
                        last_synced_at = now()
                RETURNING id
                """,
                (entity_id, zoho_contact_id, contact_name,
                 company_name, primary_email),
            )
            return cur.fetchone()[0]

    def list_by_entity(self, entity_id: UUID) -> list[Client]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.clients "
                f"WHERE entity_id = %s ORDER BY contact_name",
                (entity_id,),
            )
            return [_row(r) for r in cur.fetchall()]

    def set_tier(self, client_id: UUID, tier: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE goldman.clients SET tier = %s WHERE id = %s",
                (tier, client_id),
            )
```

- [ ] **Step 4: Run tests — should pass**

```bash
python3 -m pytest tests/test_goldman_clients_repo.py -v 2>&1 | tail -6
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add goldman_db/clients.py tests/test_goldman_clients_repo.py
git commit -m "Add ClientRepository (upsert_by_zoho_id + list + set_tier)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: VendorRepository (TDD)

**Files:**
- Create: `goldman_db/vendors.py`
- Test: `tests/test_goldman_vendors_repo.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_vendors_repo.py`:

```python
"""Tests for VendorRepository."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.vendors import Vendor, VendorRepository


def test_upsert_by_name_inserts_new():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = VendorRepository(conn)
    eid = uuid4()
    returned_id = repo.upsert_by_name(
        entity_id=eid,
        vendor_name="Helium 10",
        category="software",
        typical_amount=89.00,
        typical_currency="USD",
        typical_cadence="monthly",
        email_domain="helium10.com",
    )

    assert returned_id == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.vendors" in sql
    assert "ON CONFLICT (entity_id, vendor_name)" in sql


def test_list_by_entity_returns_vendors():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    vid = uuid4()
    eid = uuid4()
    cur.fetchall.return_value = [
        (vid, eid, None, "Helium 10", "helium10.com", "software",
         89.00, "USD", "monthly", False, None, 0, None),
    ]

    repo = VendorRepository(conn)
    vendors = repo.list_by_entity(eid)

    assert len(vendors) == 1
    assert vendors[0].vendor_name == "Helium 10"
    assert vendors[0].typical_amount == 89.00
    assert vendors[0].always_confirm is False


def test_bump_seen_increments_count_and_updates_timestamp():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = VendorRepository(conn)
    vid = uuid4()

    repo.bump_seen(vid, amount=92.00)

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.vendors" in sql
    assert "seen_count" in sql
    assert "last_seen_at" in sql
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_vendors_repo.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman_db/vendors.py`:

```python
"""Repository for goldman.vendors."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class Vendor:
    id: UUID
    entity_id: UUID
    zoho_contact_id: Optional[str]
    vendor_name: str
    email_domain: Optional[str]
    category: Optional[str]
    typical_amount: Optional[Decimal]
    typical_currency: Optional[str]
    typical_cadence: Optional[str]
    always_confirm: bool
    last_seen_at: Optional[object]   # datetime; psycopg returns datetime.datetime
    seen_count: int
    notes: Optional[str]


_COLS = """
    id, entity_id, zoho_contact_id, vendor_name, email_domain,
    category, typical_amount, typical_currency, typical_cadence,
    always_confirm, last_seen_at, seen_count, notes
"""


def _row(r) -> Vendor:
    return Vendor(
        id=r[0], entity_id=r[1], zoho_contact_id=r[2],
        vendor_name=r[3], email_domain=r[4], category=r[5],
        typical_amount=r[6], typical_currency=r[7],
        typical_cadence=r[8], always_confirm=r[9],
        last_seen_at=r[10], seen_count=r[11], notes=r[12],
    )


class VendorRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def upsert_by_name(
        self,
        *,
        entity_id: UUID,
        vendor_name: str,
        zoho_contact_id: Optional[str] = None,
        email_domain: Optional[str] = None,
        category: Optional[str] = None,
        typical_amount: Optional[float] = None,
        typical_currency: Optional[str] = None,
        typical_cadence: Optional[str] = None,
    ) -> UUID:
        """Insert or update on (entity_id, vendor_name)."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.vendors
                    (entity_id, vendor_name, zoho_contact_id, email_domain,
                     category, typical_amount, typical_currency, typical_cadence)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (entity_id, vendor_name) DO UPDATE
                    SET zoho_contact_id  = COALESCE(EXCLUDED.zoho_contact_id, goldman.vendors.zoho_contact_id),
                        email_domain     = COALESCE(EXCLUDED.email_domain, goldman.vendors.email_domain),
                        category         = COALESCE(EXCLUDED.category, goldman.vendors.category),
                        typical_amount   = COALESCE(EXCLUDED.typical_amount, goldman.vendors.typical_amount),
                        typical_currency = COALESCE(EXCLUDED.typical_currency, goldman.vendors.typical_currency),
                        typical_cadence  = COALESCE(EXCLUDED.typical_cadence, goldman.vendors.typical_cadence)
                RETURNING id
                """,
                (entity_id, vendor_name, zoho_contact_id, email_domain,
                 category, typical_amount, typical_currency, typical_cadence),
            )
            return cur.fetchone()[0]

    def list_by_entity(self, entity_id: UUID) -> list[Vendor]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.vendors "
                f"WHERE entity_id = %s ORDER BY vendor_name",
                (entity_id,),
            )
            return [_row(r) for r in cur.fetchall()]

    def bump_seen(self, vendor_id: UUID, *, amount: Optional[float] = None) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.vendors
                SET seen_count   = seen_count + 1,
                    last_seen_at = now(),
                    typical_amount = COALESCE(typical_amount, %s)
                WHERE id = %s
                """,
                (amount, vendor_id),
            )
```

- [ ] **Step 4: Run tests + Commit**

```bash
python3 -m pytest tests/test_goldman_vendors_repo.py -v 2>&1 | tail -6 && \
git add goldman_db/vendors.py tests/test_goldman_vendors_repo.py && \
git commit -m "Add VendorRepository (upsert + list + bump_seen)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 3 tests pass, commit.

---

## Task 11: BankAccountRepository (TDD)

**Files:**
- Create: `goldman_db/bank_accounts.py`
- Test: `tests/test_goldman_bank_accounts_repo.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_bank_accounts_repo.py`:

```python
"""Tests for BankAccountRepository."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.bank_accounts import BankAccount, BankAccountRepository


def test_upsert_by_label_inserts_new():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = BankAccountRepository(conn)
    eid = uuid4()
    returned = repo.upsert_by_label(
        entity_id=eid,
        provider="Wise",
        account_label="Wise USD Operating",
        currency="USD",
        account_identifier="****1234",
    )

    assert returned == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.bank_accounts" in sql


def test_list_by_entity():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    aid = uuid4()
    eid = uuid4()
    cur.fetchall.return_value = [
        (aid, eid, "Wise", "Wise USD", "USD", "****1234",
         None, None, None),
    ]

    repo = BankAccountRepository(conn)
    accts = repo.list_by_entity(eid)

    assert len(accts) == 1
    assert accts[0].provider == "Wise"
    assert accts[0].currency == "USD"


def test_set_balance_updates_row():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = BankAccountRepository(conn)
    aid = uuid4()

    repo.set_balance(aid, 45200.00)

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.bank_accounts" in sql
    assert "last_balance" in sql
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_bank_accounts_repo.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman_db/bank_accounts.py`:

```python
"""Repository for goldman.bank_accounts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class BankAccount:
    id: UUID
    entity_id: UUID
    provider: str
    account_label: str
    currency: str
    account_identifier: Optional[str]
    last_balance: Optional[Decimal]
    last_balance_at: Optional[object]
    notes: Optional[str]


_COLS = """
    id, entity_id, provider, account_label, currency,
    account_identifier, last_balance, last_balance_at, notes
"""


def _row(r) -> BankAccount:
    return BankAccount(
        id=r[0], entity_id=r[1], provider=r[2], account_label=r[3],
        currency=r[4], account_identifier=r[5],
        last_balance=r[6], last_balance_at=r[7], notes=r[8],
    )


class BankAccountRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def upsert_by_label(
        self,
        *,
        entity_id: UUID,
        provider: str,
        account_label: str,
        currency: str,
        account_identifier: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> UUID:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.bank_accounts
                    (entity_id, provider, account_label, currency,
                     account_identifier, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (entity_id, account_label) DO UPDATE
                    SET provider           = EXCLUDED.provider,
                        currency           = EXCLUDED.currency,
                        account_identifier = COALESCE(EXCLUDED.account_identifier,
                                                      goldman.bank_accounts.account_identifier),
                        notes              = COALESCE(EXCLUDED.notes,
                                                      goldman.bank_accounts.notes)
                RETURNING id
                """,
                (entity_id, provider, account_label, currency,
                 account_identifier, notes),
            )
            return cur.fetchone()[0]

    def list_by_entity(self, entity_id: UUID) -> list[BankAccount]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.bank_accounts "
                f"WHERE entity_id = %s ORDER BY provider, account_label",
                (entity_id,),
            )
            return [_row(r) for r in cur.fetchall()]

    def set_balance(self, account_id: UUID, balance: float) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.bank_accounts
                SET last_balance = %s, last_balance_at = now()
                WHERE id = %s
                """,
                (balance, account_id),
            )
```

- [ ] **Step 4: Run tests + Commit**

```bash
python3 -m pytest tests/test_goldman_bank_accounts_repo.py -v 2>&1 | tail -6 && \
git add goldman_db/bank_accounts.py tests/test_goldman_bank_accounts_repo.py && \
git commit -m "Add BankAccountRepository (upsert/list/set_balance)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 12: FactRepository (TDD)

**Files:**
- Create: `goldman_db/facts.py`
- Test: `tests/test_goldman_facts_repo.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_facts_repo.py`:

```python
"""Tests for FactRepository (minimal Phase 1 — Phase 2 extends)."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.facts import Fact, FactRepository, normalise_fact


def test_normalise_fact_lowercases_and_strips():
    assert normalise_fact("  Hello World  ") == "hello world"
    assert normalise_fact("FOO\nBAR") == "foo bar"


def test_insert_returns_new_id_and_writes_content_hash():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id, 1)   # (id, seen_count)

    repo = FactRepository(conn)
    eid = uuid4()
    returned = repo.upsert(
        entity_id=eid,
        kind="decision",
        fact="Hire a UK accountant for VAT filings",
    )

    assert returned == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.facts" in sql
    assert "ON CONFLICT" in sql
    # content_hash should be sha256 of normalised fact
    params = cur.execute.call_args[0][1]
    expected_hash = hashlib.sha256(
        b"hire a uk accountant for vat filings"
    ).hexdigest()
    assert expected_hash in params


def test_list_live_by_entity():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    fid = uuid4()
    eid = uuid4()
    cur.fetchall.return_value = [
        (fid, eid, "decision", "Hire UK accountant for VAT filings",
         "abc123hash", None, "user_explicit", 1),
    ]

    repo = FactRepository(conn)
    facts = repo.list_live_by_entity(eid)

    assert len(facts) == 1
    assert facts[0].kind == "decision"
    sql = str(cur.execute.call_args)
    assert "facts_live" in sql
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_facts_repo.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman_db/facts.py`:

```python
"""Repository for goldman.facts (minimal Phase 1 — Phase 2 extends)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class Fact:
    id: UUID
    entity_id: Optional[UUID]
    kind: str
    fact: str
    content_hash: str
    supersedes_id: Optional[UUID]
    source: str
    seen_count: int


_COLS = "id, entity_id, kind, fact, content_hash, supersedes_id, source, seen_count"


def _row(r) -> Fact:
    return Fact(
        id=r[0], entity_id=r[1], kind=r[2], fact=r[3],
        content_hash=r[4], supersedes_id=r[5],
        source=r[6], seen_count=r[7],
    )


def normalise_fact(text: str) -> str:
    """Lowercase, collapse whitespace — used to make content_hash robust to
    inconsequential differences."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _content_hash(text: str) -> str:
    return hashlib.sha256(normalise_fact(text).encode("utf-8")).hexdigest()


class FactRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def upsert(
        self,
        *,
        entity_id: Optional[UUID],
        kind: str,
        fact: str,
        source: str = "user_explicit",
    ) -> UUID:
        """Insert; on (entity_id, content_hash) conflict bump seen_count."""
        h = _content_hash(fact)
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.facts
                    (entity_id, kind, fact, content_hash, source)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (entity_id, content_hash) DO UPDATE
                    SET seen_count = goldman.facts.seen_count + 1
                RETURNING id, seen_count
                """,
                (entity_id, kind, fact, h, source),
            )
            row = cur.fetchone()
            return row[0]

    def list_live_by_entity(self, entity_id: UUID) -> list[Fact]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS} FROM goldman.facts_live
                WHERE entity_id = %s
                ORDER BY created_at DESC
                """,
                (entity_id,),
            )
            return [_row(r) for r in cur.fetchall()]
```

- [ ] **Step 4: Run tests + Commit**

```bash
python3 -m pytest tests/test_goldman_facts_repo.py -v 2>&1 | tail -6 && \
git add goldman_db/facts.py tests/test_goldman_facts_repo.py && \
git commit -m "Add FactRepository (minimal — Phase 2 will extend)

Content-hash based upsert handles dedup; supersedes_id chain handles
corrections; Phase 2 adds embedding + conflict_with columns.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 13: Extend Entity dataclass + add update_metadata

**Files:**
- Modify: `goldman_db/entities.py`
- Modify: `tests/test_goldman_entities_repo.py`

Phase 1 needs to read the entity metadata columns (`fiscal_year_end`, `registered_address`, `company_number`, `incorporation_date`) that already exist in the schema but aren't surfaced by the Phase 0 dataclass. Extend the dataclass, the SELECT, and the row mapper; then add the `update_metadata` writer.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_goldman_entities_repo.py`:

```python
from datetime import date


def test_list_all_returns_metadata_fields():
    """Entity dataclass exposes the metadata columns added for Phase 1."""
    amzg_id = uuid4()
    repo, conn, cur = _make_repo([
        (amzg_id, "amzg", "AMZ Expert Global Limited", "HK", None, "HKD",
         "914942331", "AMZG",
         "03-31", "Suite 100, HK", "HK-12345", date(2024, 1, 1)),
    ])

    entities = repo.list_all()

    assert len(entities) == 1
    assert entities[0].fiscal_year_end == "03-31"
    assert entities[0].registered_address == "Suite 100, HK"
    assert entities[0].company_number == "HK-12345"
    assert entities[0].incorporation_date == date(2024, 1, 1)


def test_update_metadata_sets_provided_fields():
    repo, conn, cur = _make_repo([])

    repo.update_metadata(
        "amzg",
        fiscal_year_end="03-31",
        registered_address="Suite 100, Hong Kong",
        company_number="HK-12345",
    )

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.entities" in sql
    assert "fiscal_year_end" in sql
    assert "registered_address" in sql
    assert "company_number" in sql
    # slug is the WHERE clause filter
    assert "slug = %s" in sql


def test_update_metadata_ignores_none_values():
    repo, conn, cur = _make_repo([])

    repo.update_metadata("amzg", fiscal_year_end="03-31", company_number=None)

    sql = str(cur.execute.call_args)
    assert "fiscal_year_end" in sql
    # None should be filtered out of the SET clause
    assert "company_number" not in sql
```

Also update the existing test fixtures to include the 4 new trailing columns (mostly None). Find this block and change all `_make_repo` rows to match the new 12-column shape:

```python
# Before (8 columns):
(amzg_id, "amzg", "AMZ Expert Global Limited", "HK", None, "HKD",
 None, "AMZG"),

# After (12 columns):
(amzg_id, "amzg", "AMZ Expert Global Limited", "HK", None, "HKD",
 None, "AMZG",
 None, None, None, None),
```

Apply to every fixture row in the file.

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_entities_repo.py -v 2>&1 | tail -10
```

Expected: existing tests start failing because `_row_to_entity` was indexed for 8 columns; new tests fail because methods/fields don't exist.

- [ ] **Step 3: Extend the dataclass + SELECT + row mapper**

Open `goldman_db/entities.py`. Replace:

```python
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
```

with (note the `from datetime import date` import at the top of the file):

```python
from datetime import date

_SELECT_COLS = """
    id, slug, legal_name, jurisdiction, parent_entity_id,
    base_currency, zoho_organization_id, zoho_credential_key,
    fiscal_year_end, registered_address, company_number, incorporation_date
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
    fiscal_year_end: Optional[str]
    registered_address: Optional[str]
    company_number: Optional[str]
    incorporation_date: Optional[date]


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
        fiscal_year_end=row[8],
        registered_address=row[9],
        company_number=row[10],
        incorporation_date=row[11],
    )
```

- [ ] **Step 4: Append `update_metadata` method**

Append to the `EntityRepository` class (after `get_by_id`):

```python
    def update_metadata(self, slug: str, **fields) -> None:
        """Update entity metadata fields. Skips fields whose value is None.

        Allowed fields: fiscal_year_end, registered_address, company_number,
        incorporation_date, zoho_organization_id. Other fields raise ValueError.
        """
        allowed = {
            "fiscal_year_end", "registered_address", "company_number",
            "incorporation_date", "zoho_organization_id",
        }
        clean = {k: v for k, v in fields.items() if v is not None}
        invalid = set(clean.keys()) - allowed
        if invalid:
            raise ValueError(f"Cannot update fields: {invalid}")
        if not clean:
            return
        set_clauses = ", ".join(f"{k} = %s" for k in clean.keys())
        params = list(clean.values()) + [slug.lower()]
        with self.conn.cursor() as cur:
            cur.execute(
                f"UPDATE goldman.entities SET {set_clauses} WHERE slug = %s",
                tuple(params),
            )
```

- [ ] **Step 5: Run tests — should pass**

```bash
python3 -m pytest tests/test_goldman_entities_repo.py -v 2>&1 | tail -10
```

Expected: all 7 tests pass (4 original now adapted + 3 new).

- [ ] **Step 6: Commit**

```bash
git add goldman_db/entities.py tests/test_goldman_entities_repo.py
git commit -m "Entity: surface metadata columns + add update_metadata

Extends Entity dataclass with fiscal_year_end, registered_address,
company_number, incorporation_date — already present in the SQL schema
since Phase 0 but not surfaced. Adds update_metadata for onboarding writes.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 14: GoldmanLLM (Anthropic wrapper)

**Files:**
- Create: `goldman/llm.py`
- Test: `tests/test_goldman_llm.py`

A thin wrapper around the Anthropic SDK that supports a single use case: send a prompt + tool definition, return the validated tool call input. Phase 1 only needs this one shape.

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_llm.py`:

```python
"""Tests for GoldmanLLM."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from goldman.llm import GoldmanLLM, LLMConfigError


def test_extract_with_tool_returns_tool_input(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")

    fake_response = MagicMock()
    # First block is the tool_use with our extracted data
    block = MagicMock()
    block.type = "tool_use"
    block.name = "submit_extraction"
    block.input = {"tax_registrations": [{"tax_type": "vat"}]}
    fake_response.content = [block]
    fake_response.stop_reason = "tool_use"

    with patch("goldman.llm.anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = fake_response
        mock_anthropic.return_value = mock_client

        llm = GoldmanLLM()
        result = llm.extract_with_tool(
            system="Extract.",
            user_text="VAT registered in UK.",
            tool_name="submit_extraction",
            tool_schema={
                "type": "object",
                "properties": {"tax_registrations": {"type": "array"}},
            },
        )

        assert result == {"tax_registrations": [{"tax_type": "vat"}]}
        # Verify the SDK was called with the right tool
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        assert call_kwargs["tools"][0]["name"] == "submit_extraction"


def test_extract_raises_when_no_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY"):
        GoldmanLLM()


def test_extract_raises_when_response_has_no_tool_use(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")

    fake_response = MagicMock()
    text_block = MagicMock()
    text_block.type = "text"
    fake_response.content = [text_block]
    fake_response.stop_reason = "end_turn"

    with patch("goldman.llm.anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = fake_response
        mock_anthropic.return_value = mock_client

        llm = GoldmanLLM()
        with pytest.raises(RuntimeError, match="did not call the tool"):
            llm.extract_with_tool(
                system="x", user_text="x",
                tool_name="t", tool_schema={"type": "object"},
            )
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_llm.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman/llm.py`:

```python
"""Thin Anthropic SDK wrapper for Goldman.

Phase 1 only needs structured extraction via tool use; later phases will
add conversation routing, streaming, and prompt caching. The wrapper keeps
that future surface area minimal.
"""

from __future__ import annotations

import os
from typing import Optional

import anthropic


DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 4096


class LLMConfigError(RuntimeError):
    """Raised when the Anthropic API key is missing or unusable."""


class GoldmanLLM:
    def __init__(self, *, model: str = DEFAULT_MODEL, max_tokens: int = DEFAULT_MAX_TOKENS):
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise LLMConfigError(
                "ANTHROPIC_API_KEY not set. Goldman needs it for the onboarding "
                "extractor (same key as HQ Hub uses for Atlas)."
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    def extract_with_tool(
        self,
        *,
        system: str,
        user_text: str,
        tool_name: str,
        tool_schema: dict,
    ) -> dict:
        """Send the prompt; force the model to call the given tool; return its input."""
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_text}],
            tools=[{
                "name": tool_name,
                "description": "Submit the structured extraction.",
                "input_schema": tool_schema,
            }],
            tool_choice={"type": "tool", "name": tool_name},
        )

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
                return dict(block.input)

        raise RuntimeError(
            f"Claude did not call the tool {tool_name!r}; "
            f"stop_reason={response.stop_reason!r}"
        )
```

- [ ] **Step 4: Run tests + Commit**

```bash
python3 -m pytest tests/test_goldman_llm.py -v 2>&1 | tail -6 && \
git add goldman/llm.py tests/test_goldman_llm.py && \
git commit -m "Add GoldmanLLM (Anthropic SDK wrapper for tool-use extraction)

Single-purpose wrapper: extract_with_tool sends a prompt + tool schema,
forces Claude to call the tool, returns the validated input dict.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 3 tests pass.

---

## Task 15: Onboarding extraction prompt + schema (TDD)

**Files:**
- Create: `goldman/onboarding/__init__.py`
- Create: `goldman/onboarding/extract.py`
- Test: `tests/test_goldman_onboarding_extract.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_onboarding_extract.py`:

```python
"""Tests for the onboarding extraction prompt + schema."""

from __future__ import annotations

from unittest.mock import MagicMock

from goldman.onboarding.extract import (
    EXTRACTION_SCHEMA,
    build_prompt,
    extract_from_dump,
)


def test_extraction_schema_has_expected_top_level_keys():
    props = EXTRACTION_SCHEMA["properties"]
    assert "tax_registrations" in props
    assert "bank_accounts" in props
    assert "vendors" in props
    assert "clients" in props
    assert "facts" in props
    assert "entity_metadata" in props


def test_build_prompt_includes_entity_context():
    system, user = build_prompt(
        entity_slug="amzg",
        entity_legal_name="AMZ Expert Global Limited",
        entity_jurisdiction="HK",
        dump="UK VAT registered as GB123456789 since 2024-03-01.",
    )

    assert "AMZ Expert Global Limited" in system
    assert "HK" in system
    assert "GB123456789" in user


def test_extract_from_dump_calls_llm_and_returns_validated_struct():
    fake_llm = MagicMock()
    fake_llm.extract_with_tool.return_value = {
        "tax_registrations": [
            {"tax_type": "vat", "jurisdiction": "GB",
             "registration_number": "GB123456789",
             "effective_from": "2024-03-01",
             "filing_cadence": "quarterly"}
        ],
        "bank_accounts": [],
        "vendors": [],
        "clients": [],
        "facts": [],
        "entity_metadata": {},
    }

    result = extract_from_dump(
        llm=fake_llm,
        entity_slug="amzg",
        entity_legal_name="AMZ Expert Global Limited",
        entity_jurisdiction="HK",
        dump="UK VAT GB123456789 since 2024-03-01, files quarterly.",
    )

    assert len(result["tax_registrations"]) == 1
    assert result["tax_registrations"][0]["jurisdiction"] == "GB"
    # The LLM call used the right tool name
    call_kwargs = fake_llm.extract_with_tool.call_args.kwargs
    assert call_kwargs["tool_name"] == "submit_extraction"
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_onboarding_extract.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman/onboarding/__init__.py`:

```python
"""Goldman onboarding flow.

Conversational brain-dump → structured rows + gap-fill.
"""
```

Create `goldman/onboarding/extract.py`:

```python
"""Onboarding extraction: prompt + tool schema + parser."""

from __future__ import annotations


EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "tax_registrations": {
            "type": "array",
            "description": "Each tax registration the entity holds.",
            "items": {
                "type": "object",
                "properties": {
                    "tax_type": {
                        "type": "string",
                        "enum": ["vat", "sales_tax", "profits_tax",
                                 "income_tax", "withholding_tax",
                                 "payroll_tax", "other"],
                    },
                    "jurisdiction": {"type": "string", "description": "e.g. HK, GB, US-TX"},
                    "registration_number": {"type": ["string", "null"]},
                    "effective_from": {"type": ["string", "null"],
                                       "description": "YYYY-MM-DD"},
                    "effective_to": {"type": ["string", "null"],
                                     "description": "YYYY-MM-DD or null"},
                    "filing_cadence": {
                        "type": ["string", "null"],
                        "enum": ["monthly", "quarterly", "annual", "irregular", None],
                    },
                    "notes": {"type": ["string", "null"]},
                },
                "required": ["tax_type", "jurisdiction"],
            },
        },
        "bank_accounts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string"},
                    "account_label": {"type": "string"},
                    "currency": {"type": "string"},
                    "account_identifier": {"type": ["string", "null"]},
                    "notes": {"type": ["string", "null"]},
                },
                "required": ["provider", "account_label", "currency"],
            },
        },
        "vendors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "vendor_name": {"type": "string"},
                    "category": {
                        "type": ["string", "null"],
                        "enum": ["hosting", "factory", "shipping", "software",
                                 "professional_services", "utilities", "other", None],
                    },
                    "email_domain": {"type": ["string", "null"]},
                    "typical_amount": {"type": ["number", "null"]},
                    "typical_currency": {"type": ["string", "null"]},
                    "typical_cadence": {
                        "type": ["string", "null"],
                        "enum": ["weekly", "monthly", "quarterly", "annual", "irregular", None],
                    },
                    "notes": {"type": ["string", "null"]},
                },
                "required": ["vendor_name"],
            },
        },
        "clients": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "contact_name": {"type": "string"},
                    "company_name": {"type": ["string", "null"]},
                    "primary_email": {"type": ["string", "null"]},
                    "tier": {"type": ["string", "null"], "enum": ["a", "b", "c", None]},
                    "notes": {"type": ["string", "null"]},
                },
                "required": ["contact_name"],
            },
        },
        "facts": {
            "type": "array",
            "description": "Free-floating facts that don't fit the structured tables.",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["target", "preference", "constraint",
                                 "commitment", "event", "decision", "note"],
                    },
                    "fact": {"type": "string"},
                },
                "required": ["kind", "fact"],
            },
        },
        "entity_metadata": {
            "type": "object",
            "description": "Updates to the entity row itself.",
            "properties": {
                "fiscal_year_end": {"type": ["string", "null"],
                                    "description": "MM-DD format"},
                "registered_address": {"type": ["string", "null"]},
                "company_number": {"type": ["string", "null"]},
                "incorporation_date": {"type": ["string", "null"],
                                       "description": "YYYY-MM-DD"},
            },
        },
    },
    "required": ["tax_registrations", "bank_accounts", "vendors",
                 "clients", "facts", "entity_metadata"],
}


SYSTEM_PROMPT_TEMPLATE = """\
You are Goldman's onboarding parser. Your job is to extract structured
company facts from the user's free-text brain-dump.

The brain-dump is about ONE legal entity:
  Slug: {slug}
  Legal name: {legal_name}
  Jurisdiction: {jurisdiction}

Extract the following from the dump:

1. TAX REGISTRATIONS — every tax registration the entity holds (VAT, sales tax,
   profits tax, income tax, withholding, payroll). Capture jurisdiction
   (HK / GB / US-TX / US-CA / etc.), registration number if mentioned, the
   start date if mentioned, and the filing cadence if mentioned.
2. BANK ACCOUNTS — every bank or fintech account (Wise, HSBC, Chase, etc.).
   Capture provider, a human-readable label, currency, and a masked identifier
   if the user mentions one.
3. VENDORS — recurring suppliers / services. Capture name, category
   (hosting/factory/shipping/software/professional_services/utilities/other),
   email domain if mentioned, typical recurring amount + currency + cadence
   if mentioned.
4. CLIENTS — customers / paying parties. Capture name and any tier/notes
   the user gives.
5. FACTS — anything else important that doesn't fit above. Examples:
   ownership percentages, key people (CPA name, lawyer name, director name),
   strategic decisions, prior advice from accountants.
   Categorise each as one of: target / preference / constraint /
   commitment / event / decision / note.
6. ENTITY METADATA — updates to the entity row itself: fiscal year end
   (MM-DD), registered address, company number, incorporation date (YYYY-MM-DD).

RULES:
- Fill fields only when you are confident from the text. Leave the rest null.
- NEVER fabricate or guess. If the user says "I might be VAT registered" do
  NOT add a tax_registration — that goes in facts as kind=note.
- Dates: use ISO format YYYY-MM-DD. For fiscal_year_end use MM-DD.
- Call the submit_extraction tool exactly once with your findings.
"""


def build_prompt(
    *,
    entity_slug: str,
    entity_legal_name: str,
    entity_jurisdiction: str,
    dump: str,
) -> tuple[str, str]:
    """Build (system, user) prompts for the onboarding extraction."""
    system = SYSTEM_PROMPT_TEMPLATE.format(
        slug=entity_slug,
        legal_name=entity_legal_name,
        jurisdiction=entity_jurisdiction,
    )
    user = f"User's brain-dump:\n\n\"\"\"\n{dump}\n\"\"\""
    return system, user


def extract_from_dump(
    *,
    llm,
    entity_slug: str,
    entity_legal_name: str,
    entity_jurisdiction: str,
    dump: str,
) -> dict:
    """Send the dump to Claude; return the validated extraction dict."""
    system, user = build_prompt(
        entity_slug=entity_slug,
        entity_legal_name=entity_legal_name,
        entity_jurisdiction=entity_jurisdiction,
        dump=dump,
    )
    return llm.extract_with_tool(
        system=system,
        user_text=user,
        tool_name="submit_extraction",
        tool_schema=EXTRACTION_SCHEMA,
    )
```

- [ ] **Step 4: Run tests + Commit**

```bash
python3 -m pytest tests/test_goldman_onboarding_extract.py -v 2>&1 | tail -6 && \
git add goldman/onboarding/__init__.py goldman/onboarding/extract.py tests/test_goldman_onboarding_extract.py && \
git commit -m "Add onboarding extraction prompt + tool schema

build_prompt() composes (system, user); extract_from_dump() invokes the
LLM tool-use path. Schema covers tax registrations, bank accounts, vendors,
clients, free-floating facts, and entity metadata updates.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 16: Onboarding writer (TDD)

**Files:**
- Create: `goldman/onboarding/writer.py`
- Test: `tests/test_goldman_onboarding_writer.py`

Takes the extraction dict and writes rows into all five tables + entity metadata.

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_onboarding_writer.py`:

```python
"""Tests for the onboarding writer."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

from goldman.onboarding.writer import OnboardingWriter, WriteSummary


def _make_writer():
    return OnboardingWriter(
        entities_repo=MagicMock(),
        tax_repo=MagicMock(),
        clients_repo=MagicMock(),
        vendors_repo=MagicMock(),
        bank_repo=MagicMock(),
        facts_repo=MagicMock(),
    )


def test_write_inserts_tax_registrations():
    w = _make_writer()
    eid = uuid4()
    new_id = uuid4()
    w.tax_repo.insert.return_value = new_id

    summary = w.write(
        entity_slug="amzg",
        entity_id=eid,
        extraction={
            "tax_registrations": [{
                "tax_type": "vat",
                "jurisdiction": "GB",
                "registration_number": "GB123456789",
                "effective_from": "2024-03-01",
                "filing_cadence": "quarterly",
            }],
            "bank_accounts": [],
            "vendors": [],
            "clients": [],
            "facts": [],
            "entity_metadata": {},
        },
    )

    w.tax_repo.insert.assert_called_once()
    kwargs = w.tax_repo.insert.call_args.kwargs
    assert kwargs["entity_id"] == eid
    assert kwargs["tax_type"] == "vat"
    assert kwargs["jurisdiction"] == "GB"
    assert kwargs["effective_from"] == date(2024, 3, 1)
    assert summary.tax_registrations_inserted == 1


def test_write_inserts_vendors_and_bank_accounts():
    w = _make_writer()
    eid = uuid4()

    summary = w.write(
        entity_slug="amzg",
        entity_id=eid,
        extraction={
            "tax_registrations": [],
            "bank_accounts": [{
                "provider": "Wise",
                "account_label": "Wise USD Operating",
                "currency": "USD",
            }],
            "vendors": [{
                "vendor_name": "Helium 10",
                "category": "software",
                "typical_amount": 89.00,
                "typical_currency": "USD",
                "typical_cadence": "monthly",
            }],
            "clients": [],
            "facts": [],
            "entity_metadata": {},
        },
    )

    w.bank_repo.upsert_by_label.assert_called_once()
    w.vendors_repo.upsert_by_name.assert_called_once()
    assert summary.bank_accounts_upserted == 1
    assert summary.vendors_upserted == 1


def test_write_updates_entity_metadata():
    w = _make_writer()
    eid = uuid4()

    w.write(
        entity_slug="amzg",
        entity_id=eid,
        extraction={
            "tax_registrations": [],
            "bank_accounts": [],
            "vendors": [],
            "clients": [],
            "facts": [],
            "entity_metadata": {
                "fiscal_year_end": "03-31",
                "registered_address": "Suite 100, HK",
                "company_number": "HK-12345",
            },
        },
    )

    w.entities_repo.update_metadata.assert_called_once_with(
        "amzg",
        fiscal_year_end="03-31",
        registered_address="Suite 100, HK",
        company_number="HK-12345",
        incorporation_date=None,
    )


def test_write_inserts_facts():
    w = _make_writer()
    eid = uuid4()

    summary = w.write(
        entity_slug="amzg",
        entity_id=eid,
        extraction={
            "tax_registrations": [],
            "bank_accounts": [],
            "vendors": [],
            "clients": [],
            "facts": [
                {"kind": "decision", "fact": "Use Wise for FX"},
                {"kind": "note", "fact": "Accountant: Jane Smith"},
            ],
            "entity_metadata": {},
        },
    )

    assert w.facts_repo.upsert.call_count == 2
    assert summary.facts_upserted == 2
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_onboarding_writer.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman/onboarding/writer.py`:

```python
"""Writes extracted onboarding data into the goldman.* tables."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional
from uuid import UUID


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


@dataclass
class WriteSummary:
    tax_registrations_inserted: int = 0
    bank_accounts_upserted: int = 0
    vendors_upserted: int = 0
    clients_upserted: int = 0
    facts_upserted: int = 0
    metadata_updated: bool = False


class OnboardingWriter:
    def __init__(
        self,
        *,
        entities_repo,
        tax_repo,
        clients_repo,
        vendors_repo,
        bank_repo,
        facts_repo,
    ):
        self.entities_repo = entities_repo
        self.tax_repo = tax_repo
        self.clients_repo = clients_repo
        self.vendors_repo = vendors_repo
        self.bank_repo = bank_repo
        self.facts_repo = facts_repo

    def write(
        self,
        *,
        entity_slug: str,
        entity_id: UUID,
        extraction: dict,
    ) -> WriteSummary:
        s = WriteSummary()

        for tr in extraction.get("tax_registrations", []):
            self.tax_repo.insert(
                entity_id=entity_id,
                tax_type=tr["tax_type"],
                jurisdiction=tr["jurisdiction"],
                registration_number=tr.get("registration_number"),
                effective_from=_parse_date(tr.get("effective_from")),
                effective_to=_parse_date(tr.get("effective_to")),
                filing_cadence=tr.get("filing_cadence"),
                notes=tr.get("notes"),
                source="extracted",
            )
            s.tax_registrations_inserted += 1

        for ba in extraction.get("bank_accounts", []):
            self.bank_repo.upsert_by_label(
                entity_id=entity_id,
                provider=ba["provider"],
                account_label=ba["account_label"],
                currency=ba["currency"],
                account_identifier=ba.get("account_identifier"),
                notes=ba.get("notes"),
            )
            s.bank_accounts_upserted += 1

        for v in extraction.get("vendors", []):
            self.vendors_repo.upsert_by_name(
                entity_id=entity_id,
                vendor_name=v["vendor_name"],
                email_domain=v.get("email_domain"),
                category=v.get("category"),
                typical_amount=v.get("typical_amount"),
                typical_currency=v.get("typical_currency"),
                typical_cadence=v.get("typical_cadence"),
            )
            s.vendors_upserted += 1

        for c in extraction.get("clients", []):
            # Clients without a zoho_contact_id can't be upserted by zoho id;
            # the Zoho sync pass fills those in later. For brain-dump-only
            # clients, we synthesise a placeholder id keyed on the name.
            self.clients_repo.upsert_by_zoho_id(
                entity_id=entity_id,
                zoho_contact_id=f"manual:{c['contact_name'].lower()}",
                contact_name=c["contact_name"],
                company_name=c.get("company_name"),
                primary_email=c.get("primary_email"),
            )
            s.clients_upserted += 1

        for f in extraction.get("facts", []):
            self.facts_repo.upsert(
                entity_id=entity_id,
                kind=f["kind"],
                fact=f["fact"],
                source="extracted",
            )
            s.facts_upserted += 1

        meta = extraction.get("entity_metadata", {}) or {}
        if any(meta.values()):
            self.entities_repo.update_metadata(
                entity_slug,
                fiscal_year_end=meta.get("fiscal_year_end"),
                registered_address=meta.get("registered_address"),
                company_number=meta.get("company_number"),
                incorporation_date=_parse_date(meta.get("incorporation_date")),
            )
            s.metadata_updated = True

        return s
```

- [ ] **Step 4: Run tests + Commit**

```bash
python3 -m pytest tests/test_goldman_onboarding_writer.py -v 2>&1 | tail -6 && \
git add goldman/onboarding/writer.py tests/test_goldman_onboarding_writer.py && \
git commit -m "Add OnboardingWriter — extraction dict to DB writes

Routes each extraction key to its repository; returns a WriteSummary
counting what landed where.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 17: Coverage check (TDD)

**Files:**
- Create: `goldman/onboarding/coverage.py`
- Test: `tests/test_goldman_onboarding_coverage.py`

Identifies which mandatory facts are missing per entity so the gap-fill loop knows what to ask.

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_onboarding_coverage.py`:

```python
"""Tests for the onboarding coverage check."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

from goldman.onboarding.coverage import Gap, missing_facts


def test_missing_facts_flags_no_tax_registration():
    eid = uuid4()
    entity = MagicMock()
    entity.id = eid
    entity.slug = "amzg"
    entity.legal_name = "AMZ Expert Global Limited"
    entity.jurisdiction = "HK"

    tax_repo = MagicMock()
    tax_repo.list_live.return_value = []
    bank_repo = MagicMock()
    bank_repo.list_by_entity.return_value = [MagicMock()]   # has bank account

    entity.fiscal_year_end = "03-31"
    entity.registered_address = "Suite 100"
    entity.incorporation_date = date(2024, 1, 1)
    entity.company_number = "HK-12345"

    gaps = missing_facts(entity, tax_repo=tax_repo, bank_repo=bank_repo)

    kinds = {g.kind for g in gaps}
    assert "tax_registration_primary" in kinds


def test_missing_facts_flags_no_bank_account():
    entity = MagicMock()
    entity.id = uuid4()
    entity.slug = "amzg"
    entity.legal_name = "AMZ Expert Global Limited"
    entity.jurisdiction = "HK"
    entity.fiscal_year_end = "03-31"
    entity.registered_address = "Suite 100"
    entity.company_number = "HK-12345"
    entity.incorporation_date = date(2024, 1, 1)

    tax_repo = MagicMock()
    tax_repo.list_live.return_value = [MagicMock(tax_type="profits_tax", jurisdiction="HK")]
    bank_repo = MagicMock()
    bank_repo.list_by_entity.return_value = []

    gaps = missing_facts(entity, tax_repo=tax_repo, bank_repo=bank_repo)

    kinds = {g.kind for g in gaps}
    assert "bank_account" in kinds


def test_missing_facts_flags_missing_metadata_fields():
    entity = MagicMock()
    entity.id = uuid4()
    entity.slug = "amzg"
    entity.legal_name = "AMZ Expert Global Limited"
    entity.jurisdiction = "HK"
    entity.fiscal_year_end = None        # missing
    entity.registered_address = None     # missing
    entity.company_number = "HK-12345"
    entity.incorporation_date = date(2024, 1, 1)

    tax_repo = MagicMock()
    tax_repo.list_live.return_value = [MagicMock()]
    bank_repo = MagicMock()
    bank_repo.list_by_entity.return_value = [MagicMock()]

    gaps = missing_facts(entity, tax_repo=tax_repo, bank_repo=bank_repo)
    kinds = {g.kind for g in gaps}
    assert "fiscal_year_end" in kinds
    assert "registered_address" in kinds


def test_missing_facts_returns_empty_when_complete():
    entity = MagicMock()
    entity.id = uuid4()
    entity.slug = "amzg"
    entity.legal_name = "AMZ Expert Global Limited"
    entity.jurisdiction = "HK"
    entity.fiscal_year_end = "03-31"
    entity.registered_address = "Suite 100, HK"
    entity.company_number = "HK-12345"
    entity.incorporation_date = date(2024, 1, 1)

    tax_repo = MagicMock()
    tax_repo.list_live.return_value = [MagicMock()]
    bank_repo = MagicMock()
    bank_repo.list_by_entity.return_value = [MagicMock()]

    gaps = missing_facts(entity, tax_repo=tax_repo, bank_repo=bank_repo)
    assert gaps == []
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_onboarding_coverage.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman/onboarding/coverage.py`:

```python
"""Onboarding coverage check.

Given an entity (already loaded) and the relevant repos, return the list
of mandatory facts that are still missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Gap:
    kind: str               # 'tax_registration_primary', 'bank_account', etc.
    prompt: str             # human-readable question for the user
    field_hints: list       # hint at expected fields (for the LLM gap-fill)


def missing_facts(entity, *, tax_repo, bank_repo) -> List[Gap]:
    """Return the gaps that need to be filled for this entity."""
    gaps: list[Gap] = []

    # Tax registration for the primary tax in the entity's jurisdiction.
    live_tax = tax_repo.list_live(entity.id)
    if not live_tax:
        primary_hint = {
            "HK": "HK profits tax",
            "US": "US federal income tax",
            "UK": "UK corporation tax",
        }.get(entity.jurisdiction, f"{entity.jurisdiction} income/profits tax")
        gaps.append(Gap(
            kind="tax_registration_primary",
            prompt=(
                f"I don't have a primary tax registration for "
                f"{entity.legal_name}. What's the {primary_hint} "
                f"registration number, and when did it become effective?"
            ),
            field_hints=["tax_type", "registration_number",
                         "effective_from", "filing_cadence"],
        ))

    # At least one bank account.
    if not bank_repo.list_by_entity(entity.id):
        gaps.append(Gap(
            kind="bank_account",
            prompt=(
                f"I don't have any bank accounts for {entity.legal_name}. "
                f"What's at least one account (provider, label, currency)?"
            ),
            field_hints=["provider", "account_label", "currency"],
        ))

    # Entity metadata fields
    if not entity.fiscal_year_end:
        gaps.append(Gap(
            kind="fiscal_year_end",
            prompt=(
                f"What is {entity.legal_name}'s fiscal year end? "
                f"(format MM-DD, e.g. 03-31 for March 31)"
            ),
            field_hints=["fiscal_year_end"],
        ))
    if not entity.registered_address:
        gaps.append(Gap(
            kind="registered_address",
            prompt=f"What is {entity.legal_name}'s registered address?",
            field_hints=["registered_address"],
        ))
    if not entity.company_number:
        gaps.append(Gap(
            kind="company_number",
            prompt=(
                f"What is {entity.legal_name}'s registration / company "
                f"number? (the official ID in {entity.jurisdiction})"
            ),
            field_hints=["company_number"],
        ))

    return gaps
```

- [ ] **Step 4: Run tests + Commit**

```bash
python3 -m pytest tests/test_goldman_onboarding_coverage.py -v 2>&1 | tail -6 && \
git add goldman/onboarding/coverage.py tests/test_goldman_onboarding_coverage.py && \
git commit -m "Add onboarding coverage check (missing_facts)

Returns Gap objects with human-readable prompts and field hints — drives
the gap-fill loop in the next task.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 18: Gap-fill orchestrator

**Files:**
- Create: `goldman/onboarding/gap_fill.py`

Loops over gaps; for each gap, prompts user via click, sends the answer to Claude (single-field extraction), writes via existing writer.

- [ ] **Step 1: Create the file**

Create `goldman/onboarding/gap_fill.py`:

```python
"""Gap-fill loop: for each Gap, prompt the user, parse, write."""

from __future__ import annotations

from typing import Callable, Optional
from uuid import UUID

import click

from goldman.onboarding.coverage import Gap


GAP_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "tax_type": {"type": ["string", "null"]},
        "jurisdiction": {"type": ["string", "null"]},
        "registration_number": {"type": ["string", "null"]},
        "effective_from": {"type": ["string", "null"]},
        "filing_cadence": {"type": ["string", "null"]},
        "provider": {"type": ["string", "null"]},
        "account_label": {"type": ["string", "null"]},
        "currency": {"type": ["string", "null"]},
        "fiscal_year_end": {"type": ["string", "null"]},
        "registered_address": {"type": ["string", "null"]},
        "company_number": {"type": ["string", "null"]},
    },
}


def _gap_extraction_prompt(gap: Gap, entity_legal_name: str, jurisdiction: str) -> str:
    return (
        f"You are extracting a single fact about {entity_legal_name} "
        f"(jurisdiction: {jurisdiction}).\n\n"
        f"Question asked: {gap.prompt}\n\n"
        f"Extract any of these fields the user provided: "
        f"{', '.join(gap.field_hints)}. Leave fields null if not provided. "
        f"Dates: YYYY-MM-DD. Fiscal year end: MM-DD."
    )


def run_gap_fill(
    *,
    entity,
    gaps: list[Gap],
    llm,
    writer,
    entity_id: UUID,
    prompt_func: Optional[Callable[[str], str]] = None,
) -> None:
    """Prompt the user for each gap, write the answer.

    prompt_func is injected for testability (default = click.prompt).
    Users can type 'skip' to defer a gap.
    """
    ask = prompt_func or (lambda msg: click.prompt(msg, default="skip"))

    for gap in gaps:
        click.echo(f"\n🤔 {gap.prompt}")
        click.echo("    (type 'skip' to defer this question)")
        answer = ask("Your answer").strip()
        if answer.lower() == "skip" or not answer:
            click.echo(f"  ↩  skipped — Goldman will ask again next time.")
            continue

        system = _gap_extraction_prompt(gap, entity.legal_name, entity.jurisdiction)
        try:
            extracted = llm.extract_with_tool(
                system=system,
                user_text=answer,
                tool_name="submit_gap_answer",
                tool_schema=GAP_EXTRACTION_SCHEMA,
            )
        except Exception as e:
            click.echo(f"  ✗  couldn't parse that — skipped. ({e})")
            continue

        # Route the extracted single-field answer to the writer through the
        # same extraction dict shape it understands.
        extraction = {
            "tax_registrations": [],
            "bank_accounts": [],
            "vendors": [],
            "clients": [],
            "facts": [],
            "entity_metadata": {},
        }
        if gap.kind == "tax_registration_primary":
            extraction["tax_registrations"].append({
                "tax_type": extracted.get("tax_type") or "profits_tax",
                "jurisdiction": extracted.get("jurisdiction") or entity.jurisdiction,
                "registration_number": extracted.get("registration_number"),
                "effective_from": extracted.get("effective_from"),
                "filing_cadence": extracted.get("filing_cadence"),
            })
        elif gap.kind == "bank_account":
            extraction["bank_accounts"].append({
                "provider": extracted.get("provider") or "Unknown",
                "account_label": extracted.get("account_label") or "Primary",
                "currency": extracted.get("currency") or entity.jurisdiction[:3].upper(),
            })
        elif gap.kind in ("fiscal_year_end", "registered_address", "company_number"):
            extraction["entity_metadata"][gap.kind] = extracted.get(gap.kind)

        writer.write(
            entity_slug=entity.slug,
            entity_id=entity_id,
            extraction=extraction,
        )
        click.echo(f"  ✓  saved.")
```

- [ ] **Step 2: Smoke-check import**

```bash
python3 -c "from goldman.onboarding.gap_fill import run_gap_fill; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add goldman/onboarding/gap_fill.py
git commit -m "Add gap-fill loop (interactive prompt -> LLM parse -> writer)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 19: Onboarding flow controller + CLI command

**Files:**
- Create: `goldman/onboarding/flow.py`
- Modify: `cli.py`

- [ ] **Step 1: Create the flow controller**

Create `goldman/onboarding/flow.py`:

```python
"""Top-level onboarding orchestrator.

Reads brain-dump from $EDITOR, calls Claude to extract structured data,
writes to all tables, runs coverage check, runs gap-fill, prints summary.
"""

from __future__ import annotations

import click

from goldman.llm import GoldmanLLM
from goldman.onboarding.coverage import missing_facts
from goldman.onboarding.extract import extract_from_dump
from goldman.onboarding.gap_fill import run_gap_fill
from goldman.onboarding.writer import OnboardingWriter
from goldman_db.bank_accounts import BankAccountRepository
from goldman_db.clients import ClientRepository
from goldman_db.connection import app_conn
from goldman_db.entities import EntityRepository
from goldman_db.facts import FactRepository
from goldman_db.tax_registrations import TaxRegistrationRepository
from goldman_db.vendors import VendorRepository


def run_onboarding(entity_slug: str) -> None:
    """End-to-end onboarding flow for a single entity."""
    click.echo(f"\nGoldman onboarding — {entity_slug}\n" + "=" * 50)

    with app_conn() as conn:
        ents = EntityRepository(conn)
        entity = ents.get_by_slug(entity_slug)
        if not entity:
            raise click.ClickException(f"Unknown entity slug: {entity_slug!r}")

    # 1. Brain dump via $EDITOR
    click.echo(
        f"\nPaste everything you know about {entity.legal_name} — "
        f"tax registrations, bank accounts, vendors, clients, decisions, "
        f"key people. Save and close the editor when done."
    )
    dump = click.edit(text="# Brain-dump for " + entity.legal_name + "\n\n").strip()
    if not dump or dump.startswith("# Brain-dump for"):
        click.echo("Empty brain-dump — skipping extraction phase.")
        extraction = {
            "tax_registrations": [], "bank_accounts": [],
            "vendors": [], "clients": [], "facts": [],
            "entity_metadata": {},
        }
    else:
        click.echo("\n→ Sending to Claude for extraction…")
        llm = GoldmanLLM()
        extraction = extract_from_dump(
            llm=llm,
            entity_slug=entity.slug,
            entity_legal_name=entity.legal_name,
            entity_jurisdiction=entity.jurisdiction,
            dump=dump,
        )
        click.echo(f"  ✓  extracted: "
                   f"{len(extraction['tax_registrations'])} tax regs, "
                   f"{len(extraction['bank_accounts'])} accounts, "
                   f"{len(extraction['vendors'])} vendors, "
                   f"{len(extraction['clients'])} clients, "
                   f"{len(extraction['facts'])} facts")

    # 2. Write to DB
    with app_conn() as conn:
        writer = OnboardingWriter(
            entities_repo=EntityRepository(conn),
            tax_repo=TaxRegistrationRepository(conn),
            clients_repo=ClientRepository(conn),
            vendors_repo=VendorRepository(conn),
            bank_repo=BankAccountRepository(conn),
            facts_repo=FactRepository(conn),
        )
        summary = writer.write(
            entity_slug=entity.slug,
            entity_id=entity.id,
            extraction=extraction,
        )

    click.echo(
        f"\n→ Wrote: "
        f"{summary.tax_registrations_inserted} tax regs, "
        f"{summary.bank_accounts_upserted} banks, "
        f"{summary.vendors_upserted} vendors, "
        f"{summary.clients_upserted} clients, "
        f"{summary.facts_upserted} facts, "
        f"metadata={summary.metadata_updated}"
    )

    # 3. Coverage check
    click.echo("\n→ Coverage check…")
    with app_conn() as conn:
        ents = EntityRepository(conn)
        entity = ents.get_by_slug(entity_slug)
        tax_repo = TaxRegistrationRepository(conn)
        bank_repo = BankAccountRepository(conn)
        gaps = missing_facts(entity, tax_repo=tax_repo, bank_repo=bank_repo)

    if not gaps:
        click.echo("  ✓  No mandatory gaps. Onboarding complete.")
        return

    click.echo(f"  ⚠  {len(gaps)} gap(s) remaining. Let's fill them.")

    # 4. Gap-fill loop
    llm = GoldmanLLM()
    with app_conn() as conn:
        writer = OnboardingWriter(
            entities_repo=EntityRepository(conn),
            tax_repo=TaxRegistrationRepository(conn),
            clients_repo=ClientRepository(conn),
            vendors_repo=VendorRepository(conn),
            bank_repo=BankAccountRepository(conn),
            facts_repo=FactRepository(conn),
        )
        run_gap_fill(
            entity=entity,
            gaps=gaps,
            llm=llm,
            writer=writer,
            entity_id=entity.id,
        )

    click.echo("\n→ Onboarding finished. Run `cli.py who --entity " +
               entity.slug + "` to review.")
```

- [ ] **Step 2: Add the CLI command**

In `cli.py`, after the `items` command (before the `db` group), add:

```python
@cli.command("onboard")
@click.option("--entity", required=True,
              help="Entity slug to onboard (amzg / seo)")
def onboard(entity):
    """Conversational onboarding for a single entity.

    Opens your editor for a brain-dump, parses it with Claude, writes the
    structured facts into Goldman's DB, then asks targeted questions for
    anything still missing.
    """
    from goldman.onboarding.flow import run_onboarding
    run_onboarding(entity.lower())
```

- [ ] **Step 3: Verify imports compile + help text**

```bash
python3 -c "import cli; print('OK')" && python3 cli.py onboard --help 2>&1 | head -8
```

Expected: `OK` then the onboard help block showing `--entity` required.

- [ ] **Step 4: Commit**

```bash
git add goldman/onboarding/flow.py cli.py
git commit -m "Add onboarding flow controller + 'cli.py onboard' command

Top-level flow: \$EDITOR brain-dump -> Claude extraction -> DB writes ->
coverage check -> interactive gap-fill -> ready to review with 'who'.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 20: Zoho contacts sync (TDD)

**Files:**
- Create: `goldman/sync/__init__.py`
- Create: `goldman/sync/zoho_contacts.py`
- Test: `tests/test_goldman_sync_zoho_contacts.py`

Categorises each Zoho contact into a `client` or a `vendor` (by `contact_type` field on Zoho) and upserts.

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_sync_zoho_contacts.py`:

```python
"""Tests for the Zoho contacts sync."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman.sync.zoho_contacts import sync_zoho_contacts


def test_sync_routes_customers_to_clients_repo():
    fake_client = MagicMock()
    # Zoho list_contacts() returns dataclasses with contact_id, contact_name, etc.
    contact = MagicMock()
    contact.contact_id = "zoho_c_123"
    contact.contact_name = "Acme"
    contact.company_name = "Acme Inc"
    contact.email = "ops@acme.com"
    fake_client.list_contacts.return_value = [contact]

    clients_repo = MagicMock()
    vendors_repo = MagicMock()
    eid = uuid4()

    result = sync_zoho_contacts(
        contact_service=fake_client,
        entity_id=eid,
        clients_repo=clients_repo,
        vendors_repo=vendors_repo,
        is_vendor=lambda c: False,   # treat all as clients
    )

    clients_repo.upsert_by_zoho_id.assert_called_once()
    kwargs = clients_repo.upsert_by_zoho_id.call_args.kwargs
    assert kwargs["zoho_contact_id"] == "zoho_c_123"
    assert kwargs["entity_id"] == eid
    assert result["clients"] == 1
    assert result["vendors"] == 0


def test_sync_routes_vendors_to_vendors_repo():
    fake_client = MagicMock()
    contact = MagicMock()
    contact.contact_id = "zoho_v_999"
    contact.contact_name = "Helium 10"
    contact.company_name = "Helium 10"
    contact.email = "billing@helium10.com"
    fake_client.list_contacts.return_value = [contact]

    clients_repo = MagicMock()
    vendors_repo = MagicMock()
    eid = uuid4()

    result = sync_zoho_contacts(
        contact_service=fake_client,
        entity_id=eid,
        clients_repo=clients_repo,
        vendors_repo=vendors_repo,
        is_vendor=lambda c: True,
    )

    vendors_repo.upsert_by_name.assert_called_once()
    kwargs = vendors_repo.upsert_by_name.call_args.kwargs
    assert kwargs["entity_id"] == eid
    assert kwargs["vendor_name"] == "Helium 10"
    assert kwargs["zoho_contact_id"] == "zoho_v_999"
    assert kwargs["email_domain"] == "helium10.com"
    assert result["vendors"] == 1
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_sync_zoho_contacts.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman/sync/__init__.py`:

```python
"""Goldman sync workers — pull from external systems into goldman tables."""
```

Create `goldman/sync/zoho_contacts.py`:

```python
"""Sync Zoho contacts into goldman.clients + goldman.vendors."""

from __future__ import annotations

from typing import Callable
from uuid import UUID


def _email_domain(email: str) -> str:
    if not email or "@" not in email:
        return ""
    return email.split("@", 1)[1].lower()


def sync_zoho_contacts(
    *,
    contact_service,
    entity_id: UUID,
    clients_repo,
    vendors_repo,
    is_vendor: Callable[[object], bool],
    page_limit: int = 5,
) -> dict:
    """Iterate Zoho contacts (paged), route to clients or vendors.

    `is_vendor(contact)` returns True if the contact should be treated as a
    vendor. For Phase 1 the default routing (set by the CLI command) is by
    the Zoho contact_type field: 'vendor' → vendors, anything else → clients.
    """
    summary = {"clients": 0, "vendors": 0}
    for page in range(1, page_limit + 1):
        contacts = contact_service.list_contacts(page=page)
        if not contacts:
            break
        for c in contacts:
            if is_vendor(c):
                vendors_repo.upsert_by_name(
                    entity_id=entity_id,
                    vendor_name=c.contact_name,
                    zoho_contact_id=c.contact_id,
                    email_domain=_email_domain(c.email),
                )
                summary["vendors"] += 1
            else:
                clients_repo.upsert_by_zoho_id(
                    entity_id=entity_id,
                    zoho_contact_id=c.contact_id,
                    contact_name=c.contact_name,
                    company_name=c.company_name,
                    primary_email=c.email,
                )
                summary["clients"] += 1
    return summary
```

- [ ] **Step 4: Run tests + Commit**

```bash
python3 -m pytest tests/test_goldman_sync_zoho_contacts.py -v 2>&1 | tail -6 && \
git add goldman/sync/__init__.py goldman/sync/zoho_contacts.py tests/test_goldman_sync_zoho_contacts.py && \
git commit -m "Add Zoho contacts sync (route to clients vs vendors)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 21: `goldman sync zoho-contacts` CLI command

**Files:**
- Modify: `cli.py`

- [ ] **Step 1: Add the sync group + command**

In `cli.py`, after the `db` group, add:

```python
# -----------------------------------------------------------------------------
# Sync workers
# -----------------------------------------------------------------------------

@cli.group()
def sync():
    """Sync external systems into Goldman."""


@sync.command("zoho-contacts")
@click.option("--entity", required=True, help="Entity slug to sync")
def sync_zoho_contacts_cmd(entity):
    """Pull Zoho contacts for this entity into goldman.clients + goldman.vendors."""
    from goldman.sync.zoho_contacts import sync_zoho_contacts
    from goldman.zoho import contact_service_for
    from goldman_db.clients import ClientRepository
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository
    from goldman_db.vendors import VendorRepository

    entity_slug = entity.lower()

    with app_conn() as conn:
        repo = EntityRepository(conn)
        ent = repo.get_by_slug(entity_slug)
        if not ent:
            raise click.ClickException(f"Unknown entity: {entity_slug}")
        contact_svc = contact_service_for(entity_slug, entity_repo=repo)
        clients_repo = ClientRepository(conn)
        vendors_repo = VendorRepository(conn)

        # Phase 1: route by Zoho's contact_type field. Zoho's Contact dataclass
        # in this repo doesn't expose contact_type yet — we treat everyone
        # as a client. Phase 3 (vendor email intake) will refine this.
        summary = sync_zoho_contacts(
            contact_service=contact_svc,
            entity_id=ent.id,
            clients_repo=clients_repo,
            vendors_repo=vendors_repo,
            is_vendor=lambda c: False,
        )

    click.echo(f"Synced for {entity_slug}: "
               f"{summary['clients']} clients, {summary['vendors']} vendors.")
```

- [ ] **Step 2: Verify**

```bash
python3 cli.py sync --help 2>&1 | head -10 && \
python3 cli.py sync zoho-contacts --help 2>&1 | head -10
```

Expected: both help blocks render, no errors.

- [ ] **Step 3: Commit**

```bash
git add cli.py
git commit -m "CLI: add 'sync zoho-contacts' command

Pulls Zoho contacts for an entity into goldman.clients (all as clients
in Phase 1; Phase 3 vendor email intake will refine the routing).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 22: WhoView aggregator (TDD)

**Files:**
- Create: `goldman/who.py`
- Test: `tests/test_goldman_who.py`

Single composable function. Returns a structured tree. A separate renderer turns it into text. Both Telegram bot (Phase 4) and Claude Code plugin (Phase 5) will reuse the structured form.

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_who.py`:

```python
"""Tests for the goldman who view."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

from goldman.who import EntitySummary, build_who_view, render_who


def test_build_who_view_includes_each_entity():
    amzg_id = uuid4()
    seo_id = uuid4()
    entities = [
        MagicMock(
            id=amzg_id, slug="amzg",
            legal_name="AMZ Expert Global Limited",
            jurisdiction="HK", parent_entity_id=None,
            base_currency="HKD",
            fiscal_year_end="03-31",
            registered_address="Suite 100",
            company_number="HK-12345",
            incorporation_date=date(2024, 1, 1),
        ),
        MagicMock(
            id=seo_id, slug="seo",
            legal_name="Specific Edge Outsourcing LLC",
            jurisdiction="US", parent_entity_id=amzg_id,
            base_currency="USD",
            fiscal_year_end=None,
            registered_address=None,
            company_number=None,
            incorporation_date=None,
        ),
    ]
    entities_repo = MagicMock()
    entities_repo.list_all.return_value = entities

    tax_repo = MagicMock()
    tax_repo.list_live.return_value = []
    bank_repo = MagicMock()
    bank_repo.list_by_entity.return_value = []
    clients_repo = MagicMock()
    clients_repo.list_by_entity.return_value = []
    vendors_repo = MagicMock()
    vendors_repo.list_by_entity.return_value = []

    view = build_who_view(
        entities_repo=entities_repo,
        tax_repo=tax_repo,
        bank_repo=bank_repo,
        clients_repo=clients_repo,
        vendors_repo=vendors_repo,
    )

    assert len(view) == 2
    assert view[0].slug == "amzg"
    assert view[0].parent_entity_id is None
    assert view[1].parent_entity_id == amzg_id


def test_render_who_includes_legal_name_and_jurisdiction():
    summary = EntitySummary(
        id=uuid4(), slug="amzg",
        legal_name="AMZ Expert Global Limited",
        jurisdiction="HK", parent_entity_id=None,
        base_currency="HKD",
        fiscal_year_end="03-31",
        registered_address="Suite 100",
        company_number="HK-12345",
        incorporation_date=None,
        tax_registrations=[],
        bank_accounts=[],
        top_clients=[],
        top_vendors=[],
    )

    output = render_who([summary])

    assert "AMZ Expert Global Limited" in output
    assert "amzg" in output
    assert "HK" in output
    assert "03-31" in output
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_who.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman/who.py`:

```python
"""Composable 'who' view of the Goldman company tree.

Build-and-render split: build_who_view returns structured data that
Telegram bot + Claude Code plugin can both consume; render_who is the
plain-text rendering used by CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from uuid import UUID


@dataclass
class EntitySummary:
    id: UUID
    slug: str
    legal_name: str
    jurisdiction: str
    parent_entity_id: Optional[UUID]
    base_currency: str
    fiscal_year_end: Optional[str]
    registered_address: Optional[str]
    company_number: Optional[str]
    incorporation_date: Optional[date]
    tax_registrations: list = field(default_factory=list)
    bank_accounts: list = field(default_factory=list)
    top_clients: list = field(default_factory=list)
    top_vendors: list = field(default_factory=list)


def build_who_view(
    *,
    entities_repo,
    tax_repo,
    bank_repo,
    clients_repo,
    vendors_repo,
    top_n: int = 5,
) -> list[EntitySummary]:
    """Build a list of EntitySummary objects, parent-first ordering."""
    result: list[EntitySummary] = []
    for ent in entities_repo.list_all():
        s = EntitySummary(
            id=ent.id, slug=ent.slug,
            legal_name=ent.legal_name,
            jurisdiction=ent.jurisdiction,
            parent_entity_id=ent.parent_entity_id,
            base_currency=ent.base_currency,
            fiscal_year_end=getattr(ent, "fiscal_year_end", None),
            registered_address=getattr(ent, "registered_address", None),
            company_number=getattr(ent, "company_number", None),
            incorporation_date=getattr(ent, "incorporation_date", None),
            tax_registrations=tax_repo.list_live(ent.id),
            bank_accounts=bank_repo.list_by_entity(ent.id),
            top_clients=clients_repo.list_by_entity(ent.id)[:top_n],
            top_vendors=vendors_repo.list_by_entity(ent.id)[:top_n],
        )
        result.append(s)
    return result


def render_who(summaries: list[EntitySummary]) -> str:
    """Render summaries as plain text, parent-first then children."""
    lines: list[str] = []
    for s in summaries:
        prefix = "└─ " if s.parent_entity_id else ""
        lines.append(f"\n{prefix}{s.legal_name} ({s.slug})")
        lines.append(f"   Jurisdiction:     {s.jurisdiction}")
        lines.append(f"   Base currency:    {s.base_currency}")
        lines.append(f"   Fiscal year end:  {s.fiscal_year_end or '— missing —'}")
        lines.append(f"   Registered addr:  {s.registered_address or '— missing —'}")
        lines.append(f"   Company number:   {s.company_number or '— missing —'}")

        lines.append("   Tax registrations:")
        if s.tax_registrations:
            for tr in s.tax_registrations:
                regn = tr.registration_number or "(no number)"
                cad = tr.filing_cadence or "(no cadence)"
                lines.append(f"     • {tr.tax_type} / {tr.jurisdiction} — {regn} [{cad}]")
        else:
            lines.append("     (none)")

        lines.append("   Bank accounts:")
        if s.bank_accounts:
            for ba in s.bank_accounts:
                lines.append(f"     • {ba.provider} — {ba.account_label} ({ba.currency})")
        else:
            lines.append("     (none)")

        lines.append(f"   Top clients ({len(s.top_clients)}):")
        for c in s.top_clients:
            tier = f" [tier {c.tier}]" if c.tier else ""
            lines.append(f"     • {c.contact_name}{tier}")

        lines.append(f"   Top vendors ({len(s.top_vendors)}):")
        for v in s.top_vendors:
            cat = f" — {v.category}" if v.category else ""
            lines.append(f"     • {v.vendor_name}{cat}")

    return "\n".join(lines).lstrip("\n")
```

- [ ] **Step 4: Run tests + Commit**

```bash
python3 -m pytest tests/test_goldman_who.py -v 2>&1 | tail -6 && \
git add goldman/who.py tests/test_goldman_who.py && \
git commit -m "Add who view (composable EntitySummary builder + text renderer)

Build-and-render split — Phase 4 Telegram and Phase 5 Claude Code plugin
will reuse the structured EntitySummary form.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 23: `goldman who` CLI command

**Files:**
- Modify: `cli.py`

- [ ] **Step 1: Add the command**

In `cli.py`, after the `sync` group, add:

```python
@cli.command("who")
def who_cmd():
    """Print Goldman's company brain: every entity + its registrations,
    bank accounts, top clients and vendors. Uses the goldman_app DB role."""
    from goldman.who import build_who_view, render_who
    from goldman_db.bank_accounts import BankAccountRepository
    from goldman_db.clients import ClientRepository
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository
    from goldman_db.tax_registrations import TaxRegistrationRepository
    from goldman_db.vendors import VendorRepository

    with app_conn() as conn:
        summaries = build_who_view(
            entities_repo=EntityRepository(conn),
            tax_repo=TaxRegistrationRepository(conn),
            bank_repo=BankAccountRepository(conn),
            clients_repo=ClientRepository(conn),
            vendors_repo=VendorRepository(conn),
        )

    click.echo(render_who(summaries))
```

- [ ] **Step 2: Verify CLI compiles + help**

```bash
python3 -c "import cli; print('OK')" && python3 cli.py who --help
```

Expected: `OK` then the who help block.

- [ ] **Step 3: Commit**

```bash
git add cli.py
git commit -m "CLI: add 'who' command — print Goldman's company brain

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 24: Full regression sweep + Phase 1 acceptance

**Files:** (no code changes; checkpoint)

- [ ] **Step 1: Run the entire test suite**

```bash
cd ~/Desktop/Obsidian/Projects/zoho-invoice-agent && python3 -m pytest -v 2>&1 | tail -10
```

Expected: every test passes. Phase 0's 46 + Phase 1's new tests (likely 30+). No regressions.

- [ ] **Step 2: Live smoke test `who` against the real DB**

```bash
python3 cli.py who
```

Expected: prints both entities (amzg + seo) with whatever metadata is currently set. Most fields will say "— missing —" until onboarding has been run; that's correct.

- [ ] **Step 3: Document acceptance + add Phase 1 facts to memory**

In ~/.claude/projects/-Users-hamburg/memory/project_goldman.md, append (under "Status"):

```markdown
- **Phase 1 code = COMPLETE** as of <today>. Tables: tax_registrations, clients, vendors, bank_accounts, facts. Repositories TDD'd. Onboarding flow (brain-dump → Claude extraction → 5-table writes → coverage check → gap-fill). Zoho contacts sync. `goldman who` command.
```

(This is a memory edit, not a git commit.)

- [ ] **Step 4: Live onboarding when Liran is ready**

When Liran is ready, he runs:
```bash
python3 cli.py onboard --entity amzg
```

This is **interactive** and **non-blocking for the plan completion**. The plan does NOT require Liran to onboard during execution — Phase 1 is "done" when the code + tests pass. Onboarding can happen any time after.

---

## Spec coverage cross-check

| Spec section | Covered by task(s) |
|---|---|
| §5.2 — tax_registrations | Task 2 (SQL) + Task 8 (repo + tests) |
| §5.2 — clients | Task 3 (SQL) + Task 9 (repo + tests) |
| §5.2 — vendors | Task 4 (SQL) + Task 10 (repo + tests) |
| §5.2 — bank_accounts | Task 5 (SQL) + Task 11 (repo + tests) |
| §6.1 — minimal facts table (Phase 2 extends) | Task 6 (SQL) + Task 12 (repo) |
| §9 step 1 (brain-dump) | Task 19 (`click.edit`) |
| §9 step 2 (Claude parses) | Tasks 14, 15 |
| §9 step 3 (store in tables) | Task 16 |
| §9 step 4 (coverage check) | Task 17 |
| §9 step 5 (one targeted question) | Task 18 |
| §9 step 6 (confirm summary) | Task 23 (`cli.py who`) — final confirm step |
| Sync from Zoho per entity | Tasks 20, 21 |
| `goldman who` composable | Tasks 22, 23 |
| Multi-entity-scoped writes | Every writer + repo carries entity_id |

All Phase 1 spec requirements have at least one implementing task.

---

## What's intentionally NOT in this plan

- `goldman_documents` + chunks (Phase 2).
- Embedding pipeline, pgvector setup, hybrid retrieval RPC (Phase 2).
- `goldman_capabilities` registry (Phase 2).
- Conflict-detection on facts (Phase 2 — supersedes_id chain is in place; conflict_with[] is the additive Phase 2 ALTER).
- Vendor email intake / Claude vision parser (Phase 3).
- Three-write filing pipeline (Phase 3).
- Telegram bot (Phase 4).
- Claude Code plugin (Phase 5).

Each gets its own plan written when the prior phase completes.
