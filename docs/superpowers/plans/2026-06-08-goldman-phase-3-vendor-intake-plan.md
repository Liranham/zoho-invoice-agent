# Goldman Phase 3 — Vendor Intake Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Goldman files vendor bills automatically. PDF/HTML/photo arrives via Gmail label or manual upload → Claude vision parses → trust gate decides auto vs confirm → three-write pipeline (Supabase Storage → Google Drive → Zoho Expenses with attached PDF) → audit-anchored, idempotent, partial-write recoverable. Foundation for Phase 4 (Telegram confirmations) and the spec's CFO-grade bookkeeping promise.

**Architecture:** One new producer table (`goldman.bills`), one new confirmation-state table (`goldman.pending_confirmations`), one new Zoho service (`zoho/expenses.py` for the Expenses API), one new Drive client (`goldman/drive/` for find-or-create-folder + upload), and a pipeline orchestrator (`goldman/bills/pipeline.py`) that runs the three writes in defined order with per-step idempotency. Claude vision via `claude-sonnet-4-6` for PDF/image parsing; tool use schema enforces structured output. Trust gate is pure Python over the vendors + bills tables. The existing `gmail/` package is generalised so vendor-bill labels (configurable per entity) sit alongside the existing Wise-transfer flow.

**Tech Stack:** Python 3.9+, existing `anthropic` (with vision), `google-api-python-client` (already present — used for Drive). New dep: `pdf2image` only if Claude vision can't accept native PDFs (it can, so skipped). Postgres + pgvector continues. Zoho Books Expenses API (REST, multipart for attachments).

---

## File Map

**Create:**
- `migrations/0016_bills.sql` — `goldman.bills` table.
- `migrations/0017_pending_confirmations.sql` — `goldman.pending_confirmations` for Telegram inline-keyboard state.
- `goldman_db/bills.py` — `Bill` dataclass + `BillRepository`.
- `goldman_db/pending_confirmations.py` — `PendingConfirmation` + repo.
- `zoho/expenses.py` — `ExpenseService` (create + attach file).
- `goldman/bills/__init__.py`
- `goldman/bills/idempotency.py` — `bill_hash(vendor, invoice_no, amount, date)`.
- `goldman/bills/parser.py` — Claude vision parser (PDF/image → structured bill).
- `goldman/bills/trust_gate.py` — auto-file vs confirm decision logic.
- `goldman/bills/pipeline.py` — three-write orchestrator with partial-write recovery.
- `goldman/drive/__init__.py`
- `goldman/drive/client.py` — Google Drive REST client.
- `goldman/drive/folders.py` — find-or-create `Goldman Bills/{entity}/{year}/{month}/`.
- `tests/test_zoho_expenses.py`
- `tests/test_goldman_bills_repo.py`
- `tests/test_goldman_pending_confirmations_repo.py`
- `tests/test_goldman_bills_idempotency.py`
- `tests/test_goldman_bills_parser.py`
- `tests/test_goldman_bills_trust_gate.py`
- `tests/test_goldman_bills_pipeline.py`
- `tests/test_goldman_drive_folders.py`
- `tests/test_goldman_drive_client.py`

**Modify:**
- `gmail/watcher.py` — extend to accept multiple labels per entity; existing Wise watch unchanged.
- `cli.py` — add `bill parse FILE`, `bill file FILE --entity SLUG`, `bill list-pending`, `bill retry ID`.
- `.env.example` — document `GOLDMAN_DRIVE_OAUTH_PATH` (or reuse existing Gmail token if scope already covers Drive — see Task 13).

---

## Task 1: Migration 0016 — goldman.bills

**Files:**
- Create: `migrations/0016_bills.sql`

The canonical bill record. Tracks the three-write progress (in_storage / in_drive / in_zoho), idempotency hash, last error.

- [ ] **Step 1: Write the SQL**

Create `migrations/0016_bills.sql`:

```sql
-- Goldman bills: canonical record of every vendor bill that lands in Goldman.
-- Per spec §7 — three-write pipeline anchored here.

CREATE TABLE IF NOT EXISTS goldman.bills (
    id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id             UUID         NOT NULL REFERENCES goldman.entities(id),
    vendor_id             UUID         REFERENCES goldman.vendors(id),
    vendor_name_at_intake TEXT         NOT NULL,
    invoice_number        TEXT,
    invoice_date          DATE,
    amount                NUMERIC(14, 2) NOT NULL,
    currency              TEXT         NOT NULL,
    due_date              DATE,
    line_items            JSONB        NOT NULL DEFAULT '[]',
    tax_amount            NUMERIC(14, 2),
    idempotency_hash      TEXT         NOT NULL UNIQUE,
    original_filename     TEXT,
    -- Three-write progress
    in_storage            BOOLEAN      NOT NULL DEFAULT FALSE,
    storage_path          TEXT,
    in_drive              BOOLEAN      NOT NULL DEFAULT FALSE,
    drive_file_id         TEXT,
    drive_url             TEXT,
    in_zoho               BOOLEAN      NOT NULL DEFAULT FALSE,
    zoho_expense_id       TEXT,
    -- Decision audit
    auto_filed            BOOLEAN      NOT NULL DEFAULT FALSE,
    confirm_required      BOOLEAN      NOT NULL DEFAULT FALSE,
    confirm_reason        TEXT,
    -- Operational
    status                TEXT         NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'partial', 'complete', 'failed', 'discarded'
    )),
    last_write_attempt_at TIMESTAMPTZ,
    last_error            TEXT,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_goldman_bills_entity_status
    ON goldman.bills(entity_id, status);
CREATE INDEX IF NOT EXISTS idx_goldman_bills_vendor
    ON goldman.bills(vendor_id) WHERE vendor_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_goldman_bills_partial
    ON goldman.bills(last_write_attempt_at)
    WHERE status IN ('partial', 'pending') AND in_storage = true;

DROP TRIGGER IF EXISTS trg_bills_updated_at ON goldman.bills;
CREATE TRIGGER trg_bills_updated_at
    BEFORE UPDATE ON goldman.bills
    FOR EACH ROW EXECUTE FUNCTION goldman.set_updated_at();
```

- [ ] **Step 2: Verify + Commit**

```bash
python3 -c "
from pathlib import Path
sql = Path('migrations/0016_bills.sql').read_text()
assert 'goldman.bills' in sql
assert 'idempotency_hash' in sql and 'UNIQUE' in sql
assert 'in_storage' in sql and 'in_drive' in sql and 'in_zoho' in sql
print('OK')
" && git add migrations/0016_bills.sql && git commit -m "Add migration 0016: goldman.bills (canonical vendor-bill record)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Migration 0017 — goldman.pending_confirmations

**Files:**
- Create: `migrations/0017_pending_confirmations.sql`

Holds the state Phase 4's Telegram inline keyboard reads from. For Phase 3, we just WRITE rows; Phase 4 will READ and REACT.

- [ ] **Step 1: Write the SQL**

Create `migrations/0017_pending_confirmations.sql`:

```sql
-- Goldman pending_confirmations: Telegram inline-keyboard state.
-- Phase 3 writes rows when trust gate says "confirm"; Phase 4 picks them up.

CREATE TABLE IF NOT EXISTS goldman.pending_confirmations (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    bill_id         UUID         NOT NULL REFERENCES goldman.bills(id) ON DELETE CASCADE,
    entity_id       UUID         NOT NULL REFERENCES goldman.entities(id),
    prompt          TEXT         NOT NULL,
    options         JSONB        NOT NULL DEFAULT '[]',
    telegram_message_id BIGINT,                                     -- set after Telegram send
    answered_at     TIMESTAMPTZ,
    answer          TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_goldman_pending_open
    ON goldman.pending_confirmations(created_at)
    WHERE answered_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_goldman_pending_bill
    ON goldman.pending_confirmations(bill_id);
```

- [ ] **Step 2: Verify + Commit**

```bash
python3 -c "
from pathlib import Path
sql = Path('migrations/0017_pending_confirmations.sql').read_text()
assert 'pending_confirmations' in sql
assert 'telegram_message_id' in sql
print('OK')
" && git add migrations/0017_pending_confirmations.sql && git commit -m "Add migration 0017: goldman.pending_confirmations (Phase 4 Telegram state)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Apply migrations 0016 + 0017 to live Supabase

- [ ] **Step 1: Run migrator**

```bash
cd ~/Desktop/Obsidian/Projects/zoho-invoice-agent && python3 cli.py db migrate
```

Expected: `Applied 2 migration(s):` listing both.

- [ ] **Step 2: Verify tables**

```bash
python3 -c "
import os, psycopg
from dotenv import load_dotenv
load_dotenv()
with psycopg.connect(os.environ['GOLDMAN_DB_APP_URL']) as conn, conn.cursor() as cur:
    for tbl in ['bills', 'pending_confirmations']:
        cur.execute(f'SELECT count(*) FROM goldman.{tbl}')
        print(f'goldman.{tbl}: {cur.fetchone()[0]} rows')
"
```

Expected: both print `0 rows`.

---

## Task 4: BillRepository (TDD)

**Files:**
- Create: `goldman_db/bills.py`
- Test: `tests/test_goldman_bills_repo.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_bills_repo.py`:

```python
"""Tests for BillRepository."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from goldman_db.bills import Bill, BillRepository, DuplicateBillError


def test_insert_returns_new_id():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = BillRepository(conn)
    eid = uuid4()
    returned = repo.insert(
        entity_id=eid,
        vendor_name_at_intake="Helium 10",
        amount=89.00,
        currency="USD",
        idempotency_hash="abc123",
        invoice_number="C0C-001",
        invoice_date=date(2026, 6, 1),
        original_filename="helium10.pdf",
    )

    assert returned == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.bills" in sql


def test_insert_raises_duplicate_when_hash_conflict():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    # Simulate unique violation
    import psycopg
    cur.execute.side_effect = psycopg.errors.UniqueViolation("duplicate")

    repo = BillRepository(conn)
    with pytest.raises(DuplicateBillError):
        repo.insert(
            entity_id=uuid4(),
            vendor_name_at_intake="x",
            amount=1,
            currency="USD",
            idempotency_hash="dup",
        )


def test_get_by_idempotency_hash():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    bid = uuid4(); eid = uuid4()
    cur.fetchone.return_value = (
        bid, eid, None, "Helium 10", "C0C-001", date(2026, 6, 1),
        89.00, "USD", None, [], None, "abc123", "helium10.pdf",
        False, None, False, None, None, False, None,
        False, False, None, "pending", None, None,
    )

    repo = BillRepository(conn)
    bill = repo.get_by_idempotency_hash("abc123")

    assert bill is not None
    assert bill.idempotency_hash == "abc123"


def test_mark_storage_done():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = BillRepository(conn)
    bid = uuid4()

    repo.mark_storage_done(bid, storage_path="amzg/2026/06/x.pdf")

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.bills" in sql
    assert "in_storage" in sql


def test_mark_drive_done():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = BillRepository(conn)
    bid = uuid4()

    repo.mark_drive_done(bid, drive_file_id="fid_xyz", drive_url="https://drive...")

    sql = str(cur.execute.call_args)
    assert "in_drive" in sql
    assert "drive_file_id" in sql


def test_mark_zoho_done():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = BillRepository(conn)
    bid = uuid4()

    repo.mark_zoho_done(bid, zoho_expense_id="E-1042")

    sql = str(cur.execute.call_args)
    assert "in_zoho" in sql
    assert "zoho_expense_id" in sql


def test_record_failure_sets_last_error_and_status():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = BillRepository(conn)
    bid = uuid4()

    repo.record_failure(bid, error="Zoho 500")

    sql = str(cur.execute.call_args)
    assert "last_error" in sql
    assert "status" in sql


def test_list_pending_partial_writes():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    repo = BillRepository(conn)
    repo.list_pending_partial_writes(limit=20)

    sql = str(cur.execute.call_args)
    assert "status" in sql
    assert "partial" in sql or "pending" in sql
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_bills_repo.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman_db/bills.py`:

```python
"""Repository for goldman.bills."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

import psycopg


class DuplicateBillError(Exception):
    """Raised when a bill with the same idempotency_hash already exists."""


@dataclass(frozen=True)
class Bill:
    id: UUID
    entity_id: UUID
    vendor_id: Optional[UUID]
    vendor_name_at_intake: str
    invoice_number: Optional[str]
    invoice_date: Optional[date]
    amount: Decimal
    currency: str
    due_date: Optional[date]
    line_items: list
    tax_amount: Optional[Decimal]
    idempotency_hash: str
    original_filename: Optional[str]
    in_storage: bool
    storage_path: Optional[str]
    in_drive: bool
    drive_file_id: Optional[str]
    drive_url: Optional[str]
    in_zoho: bool
    zoho_expense_id: Optional[str]
    auto_filed: bool
    confirm_required: bool
    confirm_reason: Optional[str]
    status: str
    last_write_attempt_at: Optional[object]
    last_error: Optional[str]


_COLS = """
    id, entity_id, vendor_id, vendor_name_at_intake, invoice_number,
    invoice_date, amount, currency, due_date, line_items, tax_amount,
    idempotency_hash, original_filename,
    in_storage, storage_path, in_drive, drive_file_id, drive_url,
    in_zoho, zoho_expense_id,
    auto_filed, confirm_required, confirm_reason,
    status, last_write_attempt_at, last_error
"""


def _row(r) -> Bill:
    return Bill(
        id=r[0], entity_id=r[1], vendor_id=r[2],
        vendor_name_at_intake=r[3], invoice_number=r[4],
        invoice_date=r[5], amount=r[6], currency=r[7],
        due_date=r[8], line_items=r[9] or [], tax_amount=r[10],
        idempotency_hash=r[11], original_filename=r[12],
        in_storage=r[13], storage_path=r[14],
        in_drive=r[15], drive_file_id=r[16], drive_url=r[17],
        in_zoho=r[18], zoho_expense_id=r[19],
        auto_filed=r[20], confirm_required=r[21], confirm_reason=r[22],
        status=r[23], last_write_attempt_at=r[24], last_error=r[25],
    )


class BillRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def insert(
        self,
        *,
        entity_id: UUID,
        vendor_name_at_intake: str,
        amount,
        currency: str,
        idempotency_hash: str,
        invoice_number: Optional[str] = None,
        invoice_date: Optional[date] = None,
        due_date: Optional[date] = None,
        line_items: Optional[list] = None,
        tax_amount: Optional[float] = None,
        original_filename: Optional[str] = None,
        vendor_id: Optional[UUID] = None,
    ) -> UUID:
        import json
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO goldman.bills
                        (entity_id, vendor_id, vendor_name_at_intake,
                         invoice_number, invoice_date, amount, currency,
                         due_date, line_items, tax_amount, idempotency_hash,
                         original_filename)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                    RETURNING id
                    """,
                    (entity_id, vendor_id, vendor_name_at_intake,
                     invoice_number, invoice_date, amount, currency,
                     due_date, json.dumps(line_items or []),
                     tax_amount, idempotency_hash, original_filename),
                )
                return cur.fetchone()[0]
        except psycopg.errors.UniqueViolation as e:
            raise DuplicateBillError(idempotency_hash) from e

    def get_by_idempotency_hash(self, idempotency_hash: str) -> Optional[Bill]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.bills WHERE idempotency_hash = %s",
                (idempotency_hash,),
            )
            row = cur.fetchone()
            return _row(row) if row else None

    def get(self, bill_id: UUID) -> Optional[Bill]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.bills WHERE id = %s",
                (bill_id,),
            )
            row = cur.fetchone()
            return _row(row) if row else None

    def mark_storage_done(self, bill_id: UUID, *, storage_path: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.bills
                SET in_storage = true, storage_path = %s,
                    last_write_attempt_at = now(),
                    status = CASE
                        WHEN in_drive AND in_zoho THEN 'complete'
                        ELSE 'partial'
                    END
                WHERE id = %s
                """,
                (storage_path, bill_id),
            )

    def mark_drive_done(
        self, bill_id: UUID, *, drive_file_id: str, drive_url: str,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.bills
                SET in_drive = true, drive_file_id = %s, drive_url = %s,
                    last_write_attempt_at = now(),
                    status = CASE
                        WHEN in_storage AND in_zoho THEN 'complete'
                        ELSE 'partial'
                    END
                WHERE id = %s
                """,
                (drive_file_id, drive_url, bill_id),
            )

    def mark_zoho_done(self, bill_id: UUID, *, zoho_expense_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.bills
                SET in_zoho = true, zoho_expense_id = %s,
                    last_write_attempt_at = now(),
                    status = CASE
                        WHEN in_storage AND in_drive THEN 'complete'
                        ELSE 'partial'
                    END
                WHERE id = %s
                """,
                (zoho_expense_id, bill_id),
            )

    def record_failure(self, bill_id: UUID, *, error: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.bills
                SET last_error = %s,
                    last_write_attempt_at = now(),
                    status = CASE
                        WHEN in_storage OR in_drive OR in_zoho THEN 'partial'
                        ELSE 'failed'
                    END
                WHERE id = %s
                """,
                (error, bill_id),
            )

    def list_pending_partial_writes(self, *, limit: int = 20) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS} FROM goldman.bills
                WHERE status IN ('partial', 'pending')
                  AND in_storage = true
                ORDER BY last_write_attempt_at ASC NULLS FIRST
                LIMIT %s
                """,
                (limit,),
            )
            return [_row(r) for r in cur.fetchall()]

    def mark_confirmation_required(
        self, bill_id: UUID, *, reason: str,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.bills
                SET confirm_required = true, confirm_reason = %s
                WHERE id = %s
                """,
                (reason, bill_id),
            )

    def mark_auto_filed(self, bill_id: UUID) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE goldman.bills SET auto_filed = true WHERE id = %s",
                (bill_id,),
            )
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_bills_repo.py -v 2>&1 | tail -12 && \
git add goldman_db/bills.py tests/test_goldman_bills_repo.py && \
git commit -m "Add BillRepository (insert + three-write progress + failure tray)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 8 tests pass.

---

## Task 5: PendingConfirmationRepository (TDD)

**Files:**
- Create: `goldman_db/pending_confirmations.py`
- Test: `tests/test_goldman_pending_confirmations_repo.py`

Minimal v1 — Phase 4 Telegram bot expands this.

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_pending_confirmations_repo.py`:

```python
"""Tests for PendingConfirmationRepository."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.pending_confirmations import (
    PendingConfirmation, PendingConfirmationRepository,
)


def test_insert_returns_new_id():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    new_id = uuid4()
    cur.fetchone.return_value = (new_id,)

    repo = PendingConfirmationRepository(conn)
    bid = uuid4(); eid = uuid4()
    returned = repo.insert(
        bill_id=bid,
        entity_id=eid,
        prompt="Helium 10 $89 — file to AMZ Expert Global?",
        options=[{"label": "✓ File", "value": "file"},
                  {"label": "✗ Hold", "value": "hold"}],
    )

    assert returned == new_id
    sql = str(cur.execute.call_args)
    assert "INSERT INTO goldman.pending_confirmations" in sql


def test_list_open():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    repo = PendingConfirmationRepository(conn)
    repo.list_open(limit=10)

    sql = str(cur.execute.call_args)
    assert "answered_at IS NULL" in sql


def test_record_answer():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = PendingConfirmationRepository(conn)
    pid = uuid4()

    repo.record_answer(pid, answer="file")

    sql = str(cur.execute.call_args)
    assert "answered_at" in sql
    assert "answer" in sql
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_pending_confirmations_repo.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman_db/pending_confirmations.py`:

```python
"""Repository for goldman.pending_confirmations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class PendingConfirmation:
    id: UUID
    bill_id: UUID
    entity_id: UUID
    prompt: str
    options: list
    telegram_message_id: Optional[int]
    answered_at: Optional[object]
    answer: Optional[str]


_COLS = """
    id, bill_id, entity_id, prompt, options,
    telegram_message_id, answered_at, answer
"""


def _row(r) -> PendingConfirmation:
    return PendingConfirmation(
        id=r[0], bill_id=r[1], entity_id=r[2],
        prompt=r[3], options=r[4] or [],
        telegram_message_id=r[5], answered_at=r[6], answer=r[7],
    )


class PendingConfirmationRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def insert(
        self,
        *,
        bill_id: UUID,
        entity_id: UUID,
        prompt: str,
        options: list,
    ) -> UUID:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.pending_confirmations
                    (bill_id, entity_id, prompt, options)
                VALUES (%s, %s, %s, %s::jsonb)
                RETURNING id
                """,
                (bill_id, entity_id, prompt, json.dumps(options)),
            )
            return cur.fetchone()[0]

    def list_open(self, *, limit: int = 50) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS} FROM goldman.pending_confirmations
                WHERE answered_at IS NULL
                ORDER BY created_at LIMIT %s
                """,
                (limit,),
            )
            return [_row(r) for r in cur.fetchall()]

    def record_answer(self, confirmation_id: UUID, *, answer: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.pending_confirmations
                SET answered_at = now(), answer = %s
                WHERE id = %s
                """,
                (answer, confirmation_id),
            )

    def attach_telegram_message(
        self, confirmation_id: UUID, *, telegram_message_id: int,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.pending_confirmations
                SET telegram_message_id = %s WHERE id = %s
                """,
                (telegram_message_id, confirmation_id),
            )
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_pending_confirmations_repo.py -v 2>&1 | tail -6 && \
git add goldman_db/pending_confirmations.py tests/test_goldman_pending_confirmations_repo.py && \
git commit -m "Add PendingConfirmationRepository (Phase 4 Telegram state)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 3 tests pass.

---

## Task 6: Idempotency hash helper (TDD)

**Files:**
- Create: `goldman/bills/__init__.py`
- Create: `goldman/bills/idempotency.py`
- Test: `tests/test_goldman_bills_idempotency.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_bills_idempotency.py`:

```python
"""Tests for bill_hash."""

from __future__ import annotations

from datetime import date

from goldman.bills.idempotency import bill_hash, normalise_vendor


def test_normalise_vendor_lowercases_and_strips_punctuation():
    assert normalise_vendor("Helium 10 INC.") == "helium 10 inc"
    assert normalise_vendor("  H10\n") == "h10"


def test_bill_hash_is_stable_for_same_inputs():
    h1 = bill_hash(
        vendor="Helium 10",
        invoice_number="C0C-001",
        amount=89.00,
        invoice_date=date(2026, 6, 1),
    )
    h2 = bill_hash(
        vendor="HELIUM 10 INC.",       # different spelling
        invoice_number="C0C-001",
        amount=89.00,
        invoice_date=date(2026, 6, 1),
    )
    # Vendor normalisation makes these different (INC vs no INC). That's
    # expected — different normalised vendor -> different hash. To make
    # them equal, the parser must normalise to the canonical form.
    assert h1 != h2

    h3 = bill_hash(
        vendor="Helium 10",
        invoice_number="C0C-001",
        amount=89.00,
        invoice_date=date(2026, 6, 1),
    )
    assert h1 == h3


def test_bill_hash_differs_on_amount():
    h1 = bill_hash(vendor="X", invoice_number="1", amount=10.00,
                   invoice_date=date(2026, 1, 1))
    h2 = bill_hash(vendor="X", invoice_number="1", amount=10.01,
                   invoice_date=date(2026, 1, 1))
    assert h1 != h2
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_bills_idempotency.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman/bills/__init__.py`:

```python
"""Goldman vendor-bill intake pipeline."""
```

Create `goldman/bills/idempotency.py`:

```python
"""Idempotency hash for vendor bills."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Optional


def normalise_vendor(name: str) -> str:
    """Lowercase + strip punctuation + collapse whitespace."""
    s = re.sub(r"[^\w\s]", "", name)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def bill_hash(
    *,
    vendor: str,
    invoice_number: Optional[str],
    amount: float,
    invoice_date: Optional[date],
) -> str:
    parts = [
        normalise_vendor(vendor),
        (invoice_number or "").strip(),
        f"{float(amount):.2f}",
        invoice_date.isoformat() if invoice_date else "",
    ]
    blob = "|".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_bills_idempotency.py -v 2>&1 | tail -6 && \
git add goldman/bills/__init__.py goldman/bills/idempotency.py tests/test_goldman_bills_idempotency.py && \
git commit -m "Add bill_hash (idempotency anchor for the three-write pipeline)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 3 tests pass.

---

## Task 7: Bill parser (Claude vision, TDD)

**Files:**
- Create: `goldman/bills/parser.py`
- Test: `tests/test_goldman_bills_parser.py`

Claude Sonnet 4.6 accepts PDFs and images natively. We send the file as a document content block + a structured-extraction tool.

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_bills_parser.py`:

```python
"""Tests for the Claude-vision bill parser."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import date

import pytest

from goldman.bills.parser import (
    PARSE_SCHEMA, BillParseResult, parse_bill_file,
)


def test_parse_schema_top_level_keys():
    props = PARSE_SCHEMA["properties"]
    assert "vendor" in props
    assert "invoice_number" in props
    assert "amount" in props
    assert "currency" in props
    assert "invoice_date" in props
    assert "billing_entity" in props


def test_parse_bill_file_returns_validated_result(tmp_path):
    f = tmp_path / "h10.pdf"
    f.write_bytes(b"%PDF-1.4\n")

    fake_llm = MagicMock()
    fake_llm.extract_from_document.return_value = {
        "vendor": "Helium 10",
        "invoice_number": "C0C735E-0091",
        "amount": 89.00,
        "currency": "USD",
        "invoice_date": "2026-06-01",
        "billing_entity": "AMZ Expert Global Limited",
        "line_items": [{"description": "Diamond plan", "amount": 89.00}],
        "tax_amount": None,
        "due_date": None,
        "parse_confidence": 0.95,
    }

    result = parse_bill_file(f, llm=fake_llm, known_entities=["amzg", "seo"])

    assert isinstance(result, BillParseResult)
    assert result.vendor == "Helium 10"
    assert result.amount == 89.00
    assert result.invoice_date == date(2026, 6, 1)
    assert result.billing_entity == "AMZ Expert Global Limited"
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_bills_parser.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman/bills/parser.py`:

```python
"""Claude-vision parser for vendor bills (PDF / image / HTML)."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional


PARSE_SCHEMA = {
    "type": "object",
    "properties": {
        "vendor": {"type": "string",
                   "description": "The supplier's name as it appears on the bill."},
        "invoice_number": {"type": ["string", "null"]},
        "amount": {"type": "number",
                   "description": "Total amount due (grand total including tax)."},
        "currency": {"type": "string",
                     "description": "ISO currency code (USD, HKD, GBP, EUR, etc.)."},
        "invoice_date": {"type": ["string", "null"],
                         "description": "YYYY-MM-DD; date issued."},
        "due_date": {"type": ["string", "null"]},
        "billing_entity": {"type": ["string", "null"],
                            "description": "Which of OUR companies is being billed (legal name on the invoice)."},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "amount": {"type": "number"},
                },
                "required": ["description", "amount"],
            },
        },
        "tax_amount": {"type": ["number", "null"]},
        "parse_confidence": {
            "type": "number",
            "description": "0.0-1.0 confidence in the parse. Below 0.7 -> trust gate forces confirm.",
        },
    },
    "required": ["vendor", "amount", "currency", "parse_confidence"],
}


@dataclass(frozen=True)
class BillParseResult:
    vendor: str
    invoice_number: Optional[str]
    amount: float
    currency: str
    invoice_date: Optional[date]
    due_date: Optional[date]
    billing_entity: Optional[str]
    line_items: list
    tax_amount: Optional[float]
    parse_confidence: float


def _safe_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except Exception:
        return None


def _build_prompt(known_entities: list) -> str:
    return (
        "You are Goldman's vendor-bill parser. Extract the structured fields "
        "from the attached document.\n\n"
        f"Known billing entities for this user: {', '.join(known_entities)}.\n"
        "If the bill is addressed to one of these, set billing_entity to "
        "its full legal name. If it's clearly a vendor's own invoice header "
        "(NOT addressed to one of OUR entities), set billing_entity to null.\n\n"
        "Rules:\n"
        "- amount = total amount due (final grand total).\n"
        "- currency = ISO code (USD/HKD/GBP/EUR/...).\n"
        "- Dates: YYYY-MM-DD.\n"
        "- parse_confidence: 0.0-1.0. Drop below 0.7 if anything is unclear, "
        "the scan is poor, or you had to guess.\n"
        "- NEVER invent fields. Use null for anything not on the document.\n\n"
        "Call submit_bill_parse with your findings."
    )


def parse_bill_file(
    file_path: Path,
    *,
    llm,
    known_entities: Optional[list] = None,
) -> BillParseResult:
    known_entities = known_entities or []
    system = _build_prompt(known_entities)
    extracted = llm.extract_from_document(
        document_path=file_path,
        system=system,
        tool_name="submit_bill_parse",
        tool_schema=PARSE_SCHEMA,
    )
    return BillParseResult(
        vendor=extracted["vendor"],
        invoice_number=extracted.get("invoice_number"),
        amount=float(extracted["amount"]),
        currency=extracted["currency"],
        invoice_date=_safe_date(extracted.get("invoice_date")),
        due_date=_safe_date(extracted.get("due_date")),
        billing_entity=extracted.get("billing_entity"),
        line_items=extracted.get("line_items") or [],
        tax_amount=extracted.get("tax_amount"),
        parse_confidence=float(extracted.get("parse_confidence", 0.0)),
    )
```

Also extend `goldman/llm.py` — append a new method `extract_from_document` to `GoldmanLLM` that accepts a file path and sends it as a document content block:

```python
    def extract_from_document(
        self,
        *,
        document_path,
        system: str,
        tool_name: str,
        tool_schema: dict,
    ) -> dict:
        """Send a file as a document content block + a tool. Return the tool input."""
        import base64
        import mimetypes
        from pathlib import Path
        path = Path(document_path)
        mime, _ = mimetypes.guess_type(path.name)
        mime = mime or "application/octet-stream"
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")

        if mime == "application/pdf":
            doc_block = {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf",
                            "data": b64},
            }
        elif mime.startswith("image/"):
            doc_block = {
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": b64},
            }
        else:
            doc_block = {"type": "text", "text": path.read_text(errors="replace")}

        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": [doc_block]}],
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

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_bills_parser.py -v 2>&1 | tail -6 && \
git add goldman/bills/parser.py goldman/llm.py tests/test_goldman_bills_parser.py && \
git commit -m "Add Claude-vision bill parser (PDF/image -> structured BillParseResult)

Extends GoldmanLLM with extract_from_document for vision input.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 2 tests pass.

---

## Task 8: Trust gate (TDD)

**Files:**
- Create: `goldman/bills/trust_gate.py`
- Test: `tests/test_goldman_bills_trust_gate.py`

Pure function over the parse + vendor history. Returns `(auto_file: bool, reason: str)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_bills_trust_gate.py`:

```python
"""Tests for the trust gate."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

from goldman.bills.trust_gate import GateDecision, decide_gate
from goldman.bills.parser import BillParseResult


def _parse(vendor="Helium 10", amount=89.00, currency="USD",
           billing_entity="AMZ Expert Global Limited", confidence=0.95):
    return BillParseResult(
        vendor=vendor, invoice_number="C0C-001", amount=amount,
        currency=currency, invoice_date=date(2026, 6, 1),
        due_date=None, billing_entity=billing_entity,
        line_items=[], tax_amount=None,
        parse_confidence=confidence,
    )


def _vendor(seen=5, typical_amount=89.00, always_confirm=False):
    v = MagicMock()
    v.id = uuid4()
    v.seen_count = seen
    v.typical_amount = typical_amount
    v.typical_currency = "USD"
    v.always_confirm = always_confirm
    return v


def test_auto_when_known_vendor_small_amount_within_band():
    parse = _parse()
    decision = decide_gate(
        parse=parse, vendor=_vendor(), known_entity_slug="amzg",
        bill_already_filed=False,
    )
    assert isinstance(decision, GateDecision)
    assert decision.auto_file is True


def test_confirm_when_amount_above_500():
    parse = _parse(amount=750.00)
    decision = decide_gate(
        parse=parse, vendor=_vendor(typical_amount=750.00),
        known_entity_slug="amzg", bill_already_filed=False,
    )
    assert decision.auto_file is False
    assert "above" in decision.reason.lower() or "ceiling" in decision.reason.lower()


def test_confirm_when_amount_deviates_more_than_15_percent():
    parse = _parse(amount=120.00)   # +35% vs typical 89
    decision = decide_gate(
        parse=parse, vendor=_vendor(typical_amount=89.00),
        known_entity_slug="amzg", bill_already_filed=False,
    )
    assert decision.auto_file is False
    assert "deviates" in decision.reason.lower() or "typical" in decision.reason.lower()


def test_confirm_when_new_vendor():
    parse = _parse()
    decision = decide_gate(
        parse=parse, vendor=None, known_entity_slug="amzg",
        bill_already_filed=False,
    )
    assert decision.auto_file is False
    assert "vendor" in decision.reason.lower()


def test_confirm_when_billing_entity_unclear():
    parse = _parse(billing_entity=None)
    decision = decide_gate(
        parse=parse, vendor=_vendor(), known_entity_slug="amzg",
        bill_already_filed=False,
    )
    assert decision.auto_file is False
    assert "entity" in decision.reason.lower()


def test_confirm_when_low_parse_confidence():
    parse = _parse(confidence=0.5)
    decision = decide_gate(
        parse=parse, vendor=_vendor(), known_entity_slug="amzg",
        bill_already_filed=False,
    )
    assert decision.auto_file is False
    assert "confidence" in decision.reason.lower()


def test_confirm_when_vendor_always_confirm_flag_set():
    parse = _parse()
    decision = decide_gate(
        parse=parse, vendor=_vendor(always_confirm=True),
        known_entity_slug="amzg", bill_already_filed=False,
    )
    assert decision.auto_file is False
    assert "confirm" in decision.reason.lower()
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_bills_trust_gate.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman/bills/trust_gate.py`:

```python
"""Trust gate: decide auto-file vs confirm.

Per spec §7.2 — auto-file requires ALL of:
  1. Known vendor (vendors.seen_count >= 3)
  2. Amount within ±15% of vendors.typical_amount
  3. Amount <= $500 absolute
  4. billing_entity matches a known entity
  5. vendors.always_confirm == false
  6. parse_confidence >= 0.7
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


AUTO_AMOUNT_CEILING = 500.0
TYPICAL_BAND_PCT = 0.15
MIN_SEEN_COUNT = 3
MIN_PARSE_CONFIDENCE = 0.7


@dataclass(frozen=True)
class GateDecision:
    auto_file: bool
    reason: str


def decide_gate(
    *,
    parse,
    vendor,                              # Vendor row or None
    known_entity_slug: Optional[str],    # resolved entity slug or None
    bill_already_filed: bool,
) -> GateDecision:
    if bill_already_filed:
        return GateDecision(False, "Bill already filed (duplicate).")

    if parse.parse_confidence < MIN_PARSE_CONFIDENCE:
        return GateDecision(
            False,
            f"Parse confidence {parse.parse_confidence:.2f} below threshold "
            f"{MIN_PARSE_CONFIDENCE}.",
        )

    if not known_entity_slug:
        return GateDecision(False, "Billing entity unclear from the document.")

    if vendor is None:
        return GateDecision(False, "New vendor — never seen before.")

    if vendor.always_confirm:
        return GateDecision(False, "Vendor flagged as always-confirm.")

    if vendor.seen_count < MIN_SEEN_COUNT:
        return GateDecision(
            False,
            f"Vendor seen only {vendor.seen_count}x (need {MIN_SEEN_COUNT}).",
        )

    if parse.amount > AUTO_AMOUNT_CEILING:
        return GateDecision(
            False,
            f"Amount {parse.amount:.2f} above ${AUTO_AMOUNT_CEILING:.0f} ceiling.",
        )

    if vendor.typical_amount:
        typical = float(vendor.typical_amount)
        if typical > 0:
            delta = abs(parse.amount - typical) / typical
            if delta > TYPICAL_BAND_PCT:
                return GateDecision(
                    False,
                    f"Amount {parse.amount:.2f} deviates {delta*100:.0f}% from "
                    f"vendor typical {typical:.2f}.",
                )

    return GateDecision(True, "Within trust gate; auto-filing.")
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_bills_trust_gate.py -v 2>&1 | tail -10 && \
git add goldman/bills/trust_gate.py tests/test_goldman_bills_trust_gate.py && \
git commit -m "Add bill trust gate (auto-file vs confirm decision)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 7 tests pass.

---

## Task 9: Zoho Expenses service (TDD)

**Files:**
- Create: `zoho/expenses.py`
- Test: `tests/test_zoho_expenses.py`

The Zoho Expenses API: POST /expenses creates the expense; POST /expenses/{id}/attachment attaches a file.

- [ ] **Step 1: Write the failing test**

Create `tests/test_zoho_expenses.py`:

```python
"""Tests for ExpenseService."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from zoho.expenses import Expense, ExpenseService


def test_create_expense_posts_correct_payload():
    client = MagicMock()
    client.post.return_value = {
        "code": 0,
        "expense": {
            "expense_id": "E-1042", "amount": 89.00, "currency_code": "USD",
            "date": "2026-06-01", "description": "Helium 10 Diamond plan",
            "status": "unpaid",
        },
    }

    svc = ExpenseService(client)
    expense = svc.create_expense(
        date="2026-06-01",
        amount=89.00,
        currency="USD",
        account_id="acc_software",
        vendor_id="zoho_vendor_h10",
        description="Helium 10 Diamond plan",
    )

    assert isinstance(expense, Expense)
    assert expense.expense_id == "E-1042"
    client.post.assert_called_once()
    args, kwargs = client.post.call_args
    assert args[0] == "expenses"
    body = kwargs["json"]
    assert body["amount"] == 89.00
    assert body["currency_code"] == "USD"


def test_attach_file_posts_multipart():
    client = MagicMock()
    client.post.return_value = {"code": 0, "message": "attached"}

    svc = ExpenseService(client)
    svc.attach_file(
        expense_id="E-1042",
        filename="helium10.pdf",
        content=b"%PDF...",
        content_type="application/pdf",
    )

    client.post.assert_called_once()
    args, kwargs = client.post.call_args
    assert args[0] == "expenses/E-1042/attachment"
    files = kwargs["files"]
    assert "attachment" in files
    fname, body, ctype = files["attachment"]
    assert fname == "helium10.pdf"
    assert body == b"%PDF..."
    assert ctype == "application/pdf"
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_zoho_expenses.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `zoho/expenses.py`:

```python
"""Zoho Books Expense service — create + attach file."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from zoho.client import ZohoClient

logger = logging.getLogger(__name__)


@dataclass
class Expense:
    expense_id: str
    amount: float
    currency_code: str
    date: str
    description: str
    status: str


class ExpenseService:
    def __init__(self, client: ZohoClient):
        self.client = client

    def _parse(self, raw: dict) -> Expense:
        return Expense(
            expense_id=raw.get("expense_id", ""),
            amount=float(raw.get("amount", 0)),
            currency_code=raw.get("currency_code", ""),
            date=raw.get("date", ""),
            description=raw.get("description", ""),
            status=raw.get("status", ""),
        )

    def create_expense(
        self,
        *,
        date: str,
        amount: float,
        currency: str,
        account_id: Optional[str] = None,
        vendor_id: Optional[str] = None,
        description: str = "",
        paid_through_account_id: Optional[str] = None,
        reference_number: Optional[str] = None,
        tax_amount: Optional[float] = None,
    ) -> Expense:
        body = {
            "date": date,
            "amount": amount,
            "currency_code": currency,
        }
        if account_id:
            body["account_id"] = account_id
        if vendor_id:
            body["vendor_id"] = vendor_id
        if description:
            body["description"] = description
        if paid_through_account_id:
            body["paid_through_account_id"] = paid_through_account_id
        if reference_number:
            body["reference_number"] = reference_number
        if tax_amount is not None:
            body["tax_amount"] = tax_amount

        data = self.client.post("expenses", json=body)
        raw = data.get("expense", data)
        return self._parse(raw)

    def attach_file(
        self,
        *,
        expense_id: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> None:
        self.client.post(
            f"expenses/{expense_id}/attachment",
            files={"attachment": (filename, content, content_type)},
        )
        logger.info("Attached %s to expense %s", filename, expense_id)
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_zoho_expenses.py -v 2>&1 | tail -6 && \
git add zoho/expenses.py tests/test_zoho_expenses.py && \
git commit -m "Add ExpenseService (create_expense + attach_file for Zoho Books)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 2 tests pass.

---

## Task 10: Google Drive folder helper (TDD)

**Files:**
- Create: `goldman/drive/__init__.py`
- Create: `goldman/drive/folders.py`
- Test: `tests/test_goldman_drive_folders.py`

Idempotent find-or-create for `Goldman Bills/{entity}/{year}/{month}/`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_drive_folders.py`:

```python
"""Tests for the Drive folder helper."""

from __future__ import annotations

from unittest.mock import MagicMock

from goldman.drive.folders import ensure_path


def test_ensure_path_returns_existing_when_found():
    drive = MagicMock()
    # Each list call returns one match
    drive.find_folder.side_effect = ["root_id", "amzg_id", "2026_id", "june_id"]

    folder_id = ensure_path(
        drive,
        ["Goldman Bills", "AMZ Expert Global Limited", "2026", "June"],
    )

    assert folder_id == "june_id"
    assert drive.find_folder.call_count == 4
    assert drive.create_folder.call_count == 0


def test_ensure_path_creates_missing_levels():
    drive = MagicMock()
    drive.find_folder.side_effect = [
        "root_id",      # Goldman Bills found
        "amzg_id",      # AMZ Expert Global Limited found
        None,           # 2026 missing
        None,           # June missing (parent 2026 was just created)
    ]
    drive.create_folder.side_effect = ["2026_id", "june_id"]

    folder_id = ensure_path(
        drive,
        ["Goldman Bills", "AMZ Expert Global Limited", "2026", "June"],
    )

    assert folder_id == "june_id"
    assert drive.create_folder.call_count == 2
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_drive_folders.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman/drive/__init__.py`:

```python
"""Goldman Google Drive integration (Phase 3 backup destination)."""
```

Create `goldman/drive/folders.py`:

```python
"""Find-or-create a nested folder path in Google Drive.

Each level lookup uses parent_id + name match.
"""

from __future__ import annotations

from typing import Optional


def ensure_path(drive_client, path_segments: list) -> str:
    """Walk a path, creating any segments that don't exist. Return leaf folder id."""
    parent_id: Optional[str] = None       # 'root' is implicit for the first call
    for name in path_segments:
        existing = drive_client.find_folder(name=name, parent_id=parent_id)
        if existing is None:
            existing = drive_client.create_folder(name=name, parent_id=parent_id)
        parent_id = existing
    return parent_id
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_drive_folders.py -v 2>&1 | tail -6 && \
git add goldman/drive/__init__.py goldman/drive/folders.py tests/test_goldman_drive_folders.py && \
git commit -m "Add ensure_path (Drive find-or-create folder walk)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 2 tests pass.

---

## Task 11: Google Drive client (TDD)

**Files:**
- Create: `goldman/drive/client.py`
- Test: `tests/test_goldman_drive_client.py`

Thin wrapper over `google-api-python-client` Drive v3. Methods: `find_folder`, `create_folder`, `upload_file`. Uses OAuth credentials from env-stashed JSON (same Bob-style pattern).

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_drive_client.py`:

```python
"""Tests for GoogleDriveClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from goldman.drive.client import GoogleDriveClient, DriveConfigError


def test_raises_when_no_credentials(monkeypatch):
    monkeypatch.delenv("GOLDMAN_DRIVE_CREDENTIALS_B64", raising=False)
    monkeypatch.delenv("GOLDMAN_DRIVE_TOKEN_B64", raising=False)

    with pytest.raises(DriveConfigError):
        GoogleDriveClient()


def test_find_folder_queries_drive_api():
    with patch("goldman.drive.client.build") as mock_build:
        svc = MagicMock()
        mock_build.return_value = svc
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "amzg_id", "name": "AMZ Expert Global Limited"}],
        }

        c = GoogleDriveClient.__new__(GoogleDriveClient)
        c._service = svc

        fid = c.find_folder(name="AMZ Expert Global Limited", parent_id="root_id")

        assert fid == "amzg_id"
        list_kwargs = svc.files.return_value.list.call_args.kwargs
        assert "AMZ Expert Global Limited" in list_kwargs["q"]
        assert "root_id" in list_kwargs["q"]


def test_create_folder_calls_drive_api():
    with patch("goldman.drive.client.build") as mock_build:
        svc = MagicMock()
        mock_build.return_value = svc
        svc.files.return_value.create.return_value.execute.return_value = {
            "id": "new_folder_id",
        }

        c = GoogleDriveClient.__new__(GoogleDriveClient)
        c._service = svc

        fid = c.create_folder(name="June", parent_id="2026_id")

        assert fid == "new_folder_id"
        body = svc.files.return_value.create.call_args.kwargs["body"]
        assert body["name"] == "June"
        assert body["mimeType"] == "application/vnd.google-apps.folder"


def test_upload_file_calls_drive_api():
    with patch("goldman.drive.client.build") as mock_build, \
         patch("goldman.drive.client.MediaIoBaseUpload") as mock_media:
        svc = MagicMock()
        mock_build.return_value = svc
        svc.files.return_value.create.return_value.execute.return_value = {
            "id": "file_xyz",
            "webViewLink": "https://drive.google.com/file/d/file_xyz/view",
        }

        c = GoogleDriveClient.__new__(GoogleDriveClient)
        c._service = svc

        result = c.upload_file(
            name="bill.pdf",
            parent_id="june_id",
            content=b"%PDF...",
            mime_type="application/pdf",
        )

        assert result["file_id"] == "file_xyz"
        assert "drive.google.com" in result["url"]
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_drive_client.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman/drive/client.py`:

```python
"""Google Drive REST client for Goldman.

Reuses Liran's personal Google OAuth (same scope structure as Bob).
Credentials + token are base64-encoded in env per the existing Gmail pattern.
"""

from __future__ import annotations

import base64
import io
import json
import os
import pickle

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload


SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class DriveConfigError(RuntimeError):
    pass


def _load_creds():
    token_b64 = os.getenv("GOLDMAN_DRIVE_TOKEN_B64", "")
    if not token_b64:
        raise DriveConfigError(
            "GOLDMAN_DRIVE_TOKEN_B64 not set. Provide a base64'd google-auth "
            "Credentials object pickled (same pattern as Bob's GOOGLE_TOKEN_B64)."
        )
    return pickle.loads(base64.b64decode(token_b64))


class GoogleDriveClient:
    def __init__(self):
        creds = _load_creds()
        self._service = build("drive", "v3", credentials=creds,
                              cache_discovery=False)

    def find_folder(self, *, name: str, parent_id):
        """Return the folder id matching (name, parent_id), or None."""
        q = (
            f"mimeType = 'application/vnd.google-apps.folder' "
            f"and name = '{name.replace(chr(39), chr(92)+chr(39))}' "
            f"and trashed = false"
        )
        if parent_id:
            q += f" and '{parent_id}' in parents"
        resp = self._service.files().list(
            q=q, fields="files(id, name)", pageSize=1,
        ).execute()
        files = resp.get("files", [])
        return files[0]["id"] if files else None

    def create_folder(self, *, name: str, parent_id) -> str:
        body = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            body["parents"] = [parent_id]
        resp = self._service.files().create(
            body=body, fields="id",
        ).execute()
        return resp["id"]

    def upload_file(
        self,
        *,
        name: str,
        parent_id: str,
        content: bytes,
        mime_type: str,
    ) -> dict:
        body = {"name": name, "parents": [parent_id]}
        media = MediaIoBaseUpload(io.BytesIO(content),
                                  mimetype=mime_type, resumable=False)
        resp = self._service.files().create(
            body=body, media_body=media,
            fields="id, webViewLink",
        ).execute()
        return {"file_id": resp["id"], "url": resp.get("webViewLink", "")}
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_drive_client.py -v 2>&1 | tail -6 && \
git add goldman/drive/client.py tests/test_goldman_drive_client.py && \
git commit -m "Add GoogleDriveClient (find/create folder + upload_file)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 4 tests pass.

---

## Task 12: Three-write pipeline orchestrator (TDD)

**Files:**
- Create: `goldman/bills/pipeline.py`
- Test: `tests/test_goldman_bills_pipeline.py`

The orchestrator runs the three writes in order, marks progress per leg, surfaces partial failures cleanly.

- [ ] **Step 1: Write the failing test**

Create `tests/test_goldman_bills_pipeline.py`:

```python
"""Tests for the three-write pipeline."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from goldman.bills.pipeline import FileResult, run_three_write_pipeline
from goldman.bills.parser import BillParseResult


def _parse(amount=89.00):
    return BillParseResult(
        vendor="Helium 10", invoice_number="C0C-001",
        amount=amount, currency="USD",
        invoice_date=date(2026, 6, 1),
        due_date=None,
        billing_entity="AMZ Expert Global Limited",
        line_items=[], tax_amount=None, parse_confidence=0.95,
    )


def test_all_three_writes_succeed(tmp_path):
    f = tmp_path / "h10.pdf"
    f.write_bytes(b"%PDF...")

    bill_id = uuid4()
    bills_repo = MagicMock()
    storage = MagicMock()
    drive = MagicMock()
    drive.upload_file.return_value = {"file_id": "fid", "url": "https://..."}
    zoho_expenses = MagicMock()
    zoho_expenses.create_expense.return_value = MagicMock(expense_id="E-1042")

    result = run_three_write_pipeline(
        bill_id=bill_id,
        file_path=f,
        mime_type="application/pdf",
        parse=_parse(),
        entity_slug="amzg",
        entity_legal_name="AMZ Expert Global Limited",
        storage=storage,
        storage_bucket="goldman-bills",
        drive_client=drive,
        drive_folder_id="june_id",
        zoho_expenses=zoho_expenses,
        bills_repo=bills_repo,
    )

    storage.upload.assert_called_once()
    drive.upload_file.assert_called_once()
    zoho_expenses.create_expense.assert_called_once()
    zoho_expenses.attach_file.assert_called_once()
    bills_repo.mark_storage_done.assert_called_once()
    bills_repo.mark_drive_done.assert_called_once()
    bills_repo.mark_zoho_done.assert_called_once()
    assert result.all_succeeded() is True


def test_drive_failure_marks_partial_and_records_error(tmp_path):
    f = tmp_path / "h10.pdf"
    f.write_bytes(b"%PDF...")

    bills_repo = MagicMock()
    storage = MagicMock()
    drive = MagicMock()
    drive.upload_file.side_effect = RuntimeError("Drive 500")
    zoho_expenses = MagicMock()

    result = run_three_write_pipeline(
        bill_id=uuid4(),
        file_path=f,
        mime_type="application/pdf",
        parse=_parse(),
        entity_slug="amzg",
        entity_legal_name="AMZ Expert Global Limited",
        storage=storage,
        storage_bucket="goldman-bills",
        drive_client=drive,
        drive_folder_id="june_id",
        zoho_expenses=zoho_expenses,
        bills_repo=bills_repo,
    )

    bills_repo.mark_storage_done.assert_called_once()
    # Drive failed -> mark_drive_done NOT called, record_failure called
    bills_repo.mark_drive_done.assert_not_called()
    bills_repo.record_failure.assert_called_once()
    # Zoho should be skipped after Drive failure
    zoho_expenses.create_expense.assert_not_called()
    assert result.all_succeeded() is False
    assert result.in_storage is True
    assert result.in_drive is False
    assert result.in_zoho is False
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_bills_pipeline.py -v 2>&1 | tail -5
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `goldman/bills/pipeline.py`:

```python
"""Three-write pipeline: Supabase Storage -> Google Drive -> Zoho Expenses.

Per spec §7.1 — order is Supabase first (audit anchor), then Drive (human
backup), then Zoho (the ledger). Each leg is independently retriable.
"""

from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(name: str) -> str:
    return _SAFE_NAME.sub("_", name)


@dataclass
class FileResult:
    bill_id: UUID
    in_storage: bool
    in_drive: bool
    in_zoho: bool
    storage_path: Optional[str]
    drive_file_id: Optional[str]
    drive_url: Optional[str]
    zoho_expense_id: Optional[str]
    error: Optional[str]

    def all_succeeded(self) -> bool:
        return self.in_storage and self.in_drive and self.in_zoho


def _storage_path(*, entity_slug: str, invoice_date: Optional[date], filename: str) -> str:
    d = invoice_date or date.today()
    return f"{entity_slug}/{d.year}/{d.month:02d}/{_safe_filename(filename)}"


def run_three_write_pipeline(
    *,
    bill_id: UUID,
    file_path: Path,
    mime_type: str,
    parse,
    entity_slug: str,
    entity_legal_name: str,
    storage,
    storage_bucket: str,
    drive_client,
    drive_folder_id: str,
    zoho_expenses,
    bills_repo,
) -> FileResult:
    content = file_path.read_bytes()
    storage_path = _storage_path(
        entity_slug=entity_slug,
        invoice_date=parse.invoice_date,
        filename=file_path.name,
    )

    result = FileResult(
        bill_id=bill_id,
        in_storage=False, in_drive=False, in_zoho=False,
        storage_path=None, drive_file_id=None, drive_url=None,
        zoho_expense_id=None, error=None,
    )

    # 1. SUPABASE STORAGE
    try:
        storage.upload(
            bucket=storage_bucket, path=storage_path,
            content=content, content_type=mime_type,
        )
        bills_repo.mark_storage_done(bill_id, storage_path=storage_path)
        result.in_storage = True
        result.storage_path = storage_path
    except Exception as e:
        msg = f"Storage write failed: {e}"
        logger.exception(msg)
        bills_repo.record_failure(bill_id, error=msg)
        result.error = msg
        return result   # Without Supabase, we don't trust the rest.

    # 2. GOOGLE DRIVE
    try:
        upload = drive_client.upload_file(
            name=file_path.name,
            parent_id=drive_folder_id,
            content=content,
            mime_type=mime_type,
        )
        bills_repo.mark_drive_done(
            bill_id,
            drive_file_id=upload["file_id"],
            drive_url=upload.get("url", ""),
        )
        result.in_drive = True
        result.drive_file_id = upload["file_id"]
        result.drive_url = upload.get("url", "")
    except Exception as e:
        msg = f"Drive write failed: {e}"
        logger.exception(msg)
        bills_repo.record_failure(bill_id, error=msg)
        result.error = msg
        return result    # Skip Zoho — retry can pick up from here.

    # 3. ZOHO EXPENSES
    try:
        expense = zoho_expenses.create_expense(
            date=parse.invoice_date.isoformat() if parse.invoice_date else date.today().isoformat(),
            amount=parse.amount,
            currency=parse.currency,
            description=(
                f"{parse.vendor} {parse.invoice_number or ''}".strip()
                + (f" ({entity_legal_name})" if entity_legal_name else "")
            ),
        )
        zoho_expenses.attach_file(
            expense_id=expense.expense_id,
            filename=file_path.name,
            content=content,
            content_type=mime_type,
        )
        bills_repo.mark_zoho_done(bill_id, zoho_expense_id=expense.expense_id)
        result.in_zoho = True
        result.zoho_expense_id = expense.expense_id
    except Exception as e:
        msg = f"Zoho write failed: {e}"
        logger.exception(msg)
        bills_repo.record_failure(bill_id, error=msg)
        result.error = msg
        return result

    return result
```

- [ ] **Step 4: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_bills_pipeline.py -v 2>&1 | tail -6 && \
git add goldman/bills/pipeline.py tests/test_goldman_bills_pipeline.py && \
git commit -m "Add three-write pipeline (Storage -> Drive -> Zoho Expenses)

Per-leg idempotency via bill row state; partial failures recoverable.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 2 tests pass.

---

## Task 13: CLI — `bill parse FILE`, `bill file FILE`, `bill list-pending`, `bill retry ID`

**Files:**
- Modify: `cli.py`
- Modify: `.env.example`

- [ ] **Step 1: Add the bill group + commands**

In `cli.py`, after the `document` group, add:

```python
# -----------------------------------------------------------------------------
# Bills
# -----------------------------------------------------------------------------

@cli.group()
def bill():
    """Goldman vendor-bill intake pipeline."""


@bill.command("parse")
@click.argument("file", type=click.Path(exists=True))
def bill_parse(file):
    """Parse a single bill file via Claude vision. Read-only — no DB writes."""
    from pathlib import Path
    from goldman.bills.parser import parse_bill_file
    from goldman.llm import GoldmanLLM
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository

    llm = GoldmanLLM()
    with app_conn() as conn:
        entities = EntityRepository(conn).list_all()
    known = [e.legal_name for e in entities]

    result = parse_bill_file(Path(file), llm=llm, known_entities=known)

    click.echo(f"  vendor:           {result.vendor}")
    click.echo(f"  invoice_number:   {result.invoice_number or '-'}")
    click.echo(f"  amount:           {result.amount} {result.currency}")
    click.echo(f"  invoice_date:     {result.invoice_date}")
    click.echo(f"  billing_entity:   {result.billing_entity or '-'}")
    click.echo(f"  parse_confidence: {result.parse_confidence}")


@bill.command("file")
@click.option("--entity", default=None,
              help="Force entity slug (overrides parser's billing_entity).")
@click.argument("file", type=click.Path(exists=True))
def bill_file(entity, file):
    """End-to-end: parse + trust gate + three-write pipeline."""
    from pathlib import Path
    import mimetypes

    from goldman.bills.idempotency import bill_hash
    from goldman.bills.parser import parse_bill_file
    from goldman.bills.pipeline import run_three_write_pipeline
    from goldman.bills.trust_gate import decide_gate
    from goldman.drive.client import GoogleDriveClient
    from goldman.drive.folders import ensure_path
    from goldman.llm import GoldmanLLM
    from goldman.storage import SupabaseStorage
    from goldman.zoho import for_entity
    from goldman_db.bills import BillRepository, DuplicateBillError
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository
    from goldman_db.pending_confirmations import PendingConfirmationRepository
    from goldman_db.vendors import VendorRepository
    from zoho.expenses import ExpenseService

    p = Path(file)
    mime, _ = mimetypes.guess_type(p.name)
    mime = mime or "application/octet-stream"

    llm = GoldmanLLM()

    # 1. Parse
    with app_conn() as conn:
        entities = EntityRepository(conn).list_all()
    known = [e.legal_name for e in entities]
    parse = parse_bill_file(p, llm=llm, known_entities=known)

    # 2. Resolve entity
    entity_slug = entity.lower() if entity else None
    if not entity_slug:
        # Match parser's billing_entity against entities by legal name.
        if parse.billing_entity:
            for e in entities:
                if e.legal_name.strip().lower() == parse.billing_entity.strip().lower():
                    entity_slug = e.slug
                    break

    if not entity_slug:
        raise click.ClickException(
            "Cannot resolve billing entity from parse. Pass --entity SLUG."
        )

    with app_conn() as conn:
        ent = EntityRepository(conn).get_by_slug(entity_slug)
        vendors_repo = VendorRepository(conn)
        bills_repo = BillRepository(conn)
        pending_repo = PendingConfirmationRepository(conn)

        # 3. Resolve vendor
        all_vendors = vendors_repo.list_by_entity(ent.id)
        from goldman.bills.idempotency import normalise_vendor
        norm = normalise_vendor(parse.vendor)
        vendor = next(
            (v for v in all_vendors if normalise_vendor(v.vendor_name) == norm),
            None,
        )

        # 4. Compute idempotency hash + early dup check
        h = bill_hash(
            vendor=parse.vendor,
            invoice_number=parse.invoice_number,
            amount=parse.amount,
            invoice_date=parse.invoice_date,
        )
        existing = bills_repo.get_by_idempotency_hash(h)
        if existing is not None:
            click.echo(f"  -> already filed (bill {existing.id}, status={existing.status})")
            return

        # 5. Insert bill row (still pending)
        try:
            bill_id = bills_repo.insert(
                entity_id=ent.id,
                vendor_id=vendor.id if vendor else None,
                vendor_name_at_intake=parse.vendor,
                invoice_number=parse.invoice_number,
                invoice_date=parse.invoice_date,
                amount=parse.amount,
                currency=parse.currency,
                idempotency_hash=h,
                due_date=parse.due_date,
                line_items=parse.line_items,
                tax_amount=parse.tax_amount,
                original_filename=p.name,
            )
        except DuplicateBillError:
            click.echo("  -> race: duplicate found on insert; skipping.")
            return

        # 6. Trust gate
        decision = decide_gate(
            parse=parse, vendor=vendor,
            known_entity_slug=entity_slug,
            bill_already_filed=False,
        )

        if not decision.auto_file:
            bills_repo.mark_confirmation_required(bill_id, reason=decision.reason)
            pending_id = pending_repo.insert(
                bill_id=bill_id, entity_id=ent.id,
                prompt=(
                    f"{parse.vendor} {parse.amount} {parse.currency} — "
                    f"file to {ent.legal_name}? Reason: {decision.reason}"
                ),
                options=[
                    {"label": "Yes, file", "value": f"file:{entity_slug}"},
                    {"label": "Hold", "value": "hold"},
                    {"label": "Discard", "value": "discard"},
                ],
            )
            click.echo(
                f"  -> confirmation required: {decision.reason}\n"
                f"     pending_id={pending_id}; waiting for Telegram (Phase 4)."
            )
            return

    # 7. Auto-file: run the three-write pipeline
    storage = SupabaseStorage()
    drive_client = GoogleDriveClient()
    zoho_client = for_entity(entity_slug, entity_repo=EntityRepository(app_conn().__enter__()))
    zoho_expenses = ExpenseService(zoho_client)

    # Folder: Goldman Bills / {entity_legal_name} / {YYYY} / {Month name}
    d = parse.invoice_date or date.today()
    month_name = ["January","February","March","April","May","June",
                  "July","August","September","October","November","December"][d.month - 1]
    folder_id = ensure_path(drive_client, [
        "Goldman Bills", ent.legal_name, str(d.year), month_name,
    ])

    with app_conn() as conn:
        bills_repo = BillRepository(conn)
        bills_repo.mark_auto_filed(bill_id)
        result = run_three_write_pipeline(
            bill_id=bill_id,
            file_path=p,
            mime_type=mime,
            parse=parse,
            entity_slug=ent.slug,
            entity_legal_name=ent.legal_name,
            storage=storage,
            storage_bucket="goldman-bills",
            drive_client=drive_client,
            drive_folder_id=folder_id,
            zoho_expenses=zoho_expenses,
            bills_repo=bills_repo,
        )

    if result.all_succeeded():
        click.echo(
            f"  ok filed {parse.vendor} {parse.amount} {parse.currency} -> "
            f"{ent.legal_name}; Zoho expense {result.zoho_expense_id}"
        )
    else:
        click.echo(
            f"  partial: storage={result.in_storage} drive={result.in_drive} "
            f"zoho={result.in_zoho}; error={result.error}"
        )


@bill.command("list-pending")
def bill_list_pending():
    """List bills with status partial/pending (failure tray)."""
    from goldman_db.bills import BillRepository
    from goldman_db.connection import app_conn

    with app_conn() as conn:
        bills = BillRepository(conn).list_pending_partial_writes(limit=50)

    if not bills:
        click.echo("(no pending bills)")
        return
    for b in bills:
        click.echo(
            f"  {b.vendor_name_at_intake} {b.amount} {b.currency} | "
            f"storage={b.in_storage} drive={b.in_drive} zoho={b.in_zoho} | "
            f"id={b.id} | {b.last_error or ''}"
        )


@bill.command("retry")
@click.argument("bill_id")
def bill_retry(bill_id):
    """Retry the failed legs for a partial bill."""
    from pathlib import Path
    from uuid import UUID
    from goldman.bills.pipeline import run_three_write_pipeline
    from goldman.bills.parser import BillParseResult
    from goldman.drive.client import GoogleDriveClient
    from goldman.drive.folders import ensure_path
    from goldman.storage import SupabaseStorage
    from goldman.zoho import for_entity
    from goldman_db.bills import BillRepository
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository
    from zoho.expenses import ExpenseService

    # For Phase 3 v1, retry expects the original file to still be on disk
    # at the path the user passes via env. Production retry will fetch from
    # Supabase Storage; we keep it simple here.
    src = os.environ.get("GOLDMAN_BILL_RETRY_PATH", "")
    if not src or not Path(src).exists():
        raise click.ClickException(
            "Set GOLDMAN_BILL_RETRY_PATH to the original file path to retry."
        )

    with app_conn() as conn:
        b = BillRepository(conn).get(UUID(bill_id))
        if not b:
            raise click.ClickException(f"No bill {bill_id}")
        ent = EntityRepository(conn).get_by_id(b.entity_id)

    parse = BillParseResult(
        vendor=b.vendor_name_at_intake, invoice_number=b.invoice_number,
        amount=float(b.amount), currency=b.currency,
        invoice_date=b.invoice_date, due_date=b.due_date,
        billing_entity=ent.legal_name,
        line_items=b.line_items, tax_amount=float(b.tax_amount or 0) or None,
        parse_confidence=1.0,
    )

    storage = SupabaseStorage()
    drive_client = GoogleDriveClient()
    zoho_client = for_entity(ent.slug, entity_repo=EntityRepository(app_conn().__enter__()))
    zoho_expenses = ExpenseService(zoho_client)

    d = b.invoice_date or date.today()
    month_name = ["January","February","March","April","May","June",
                  "July","August","September","October","November","December"][d.month - 1]
    folder_id = ensure_path(drive_client, [
        "Goldman Bills", ent.legal_name, str(d.year), month_name,
    ])

    with app_conn() as conn:
        bills_repo = BillRepository(conn)
        result = run_three_write_pipeline(
            bill_id=b.id, file_path=Path(src),
            mime_type="application/pdf", parse=parse,
            entity_slug=ent.slug, entity_legal_name=ent.legal_name,
            storage=storage, storage_bucket="goldman-bills",
            drive_client=drive_client, drive_folder_id=folder_id,
            zoho_expenses=zoho_expenses, bills_repo=bills_repo,
        )

    click.echo(
        f"  retry: storage={result.in_storage} drive={result.in_drive} "
        f"zoho={result.in_zoho}"
    )
```

Also append `import os` near the top of `cli.py` if not already present (search before adding).

- [ ] **Step 2: Update .env.example with Drive credentials**

Append to `.env.example`:

```bash

# ============================================================================
# Goldman Phase 3 — Google Drive + Gmail (for vendor-bill intake)
# ============================================================================
# Google Drive OAuth — base64'd pickled google-auth Credentials object.
# Same pattern as Bob's GOOGLE_TOKEN_B64. Easiest path: generate locally via
# scripts/generate_drive_token.py (TBD; for v1, reuse Bob's token if it
# already has drive.file scope).
GOLDMAN_DRIVE_TOKEN_B64=

# (Gmail intake reuses existing GMAIL_CREDENTIALS_B64 / GMAIL_TOKEN_B64.)
```

- [ ] **Step 3: Verify CLI compiles + help**

```bash
python3 -c "import cli; print('OK')" && python3 cli.py bill --help 2>&1 | head -12
```

Expected: `OK` then the bill group help.

- [ ] **Step 4: Commit**

```bash
git add cli.py .env.example && git commit -m "CLI: add 'bill' group (parse / file / list-pending / retry)

Per spec §7 — full three-write pipeline behind 'bill file', read-only
preview via 'bill parse', failure tray via 'bill list-pending', and
manual leg-retry via 'bill retry'.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 14: Apply migrations 0016 + 0017 + final regression

- [ ] **Step 1: Apply migrations**

```bash
cd ~/Desktop/Obsidian/Projects/zoho-invoice-agent && python3 cli.py db migrate
```

Expected: `Applied 2 migration(s):` (0016, 0017).

- [ ] **Step 2: Full test sweep**

```bash
python3 -m pytest -v 2>&1 | tail -5
```

Expected: every test passes (Phase 0/1/2's 112 + Phase 3's new tests ≈ 140).

- [ ] **Step 3: Verify CLI surface**

```bash
python3 cli.py --help 2>&1 | tail -25 && python3 cli.py bill --help 2>&1 | tail -10
```

Expected: `bill` shows in main commands; subcommands `parse, file, list-pending, retry` shown.

- [ ] **Step 4: Live config-error verification (without Drive token)**

```bash
unset GOLDMAN_DRIVE_TOKEN_B64
echo "test" > /tmp/g_bill.txt
python3 cli.py bill file --entity amzg /tmp/g_bill.txt 2>&1 | tail -3 ; rm -f /tmp/g_bill.txt
```

Expected: clear error from Claude vision (since the test file isn't a real bill) OR a clear DriveConfigError when the pipeline reaches Drive — both are acceptable boundary signals.

- [ ] **Step 5: Update memory**

Append to `~/.claude/projects/-Users-hamburg/memory/project_goldman.md` (under Status):

```markdown
- **Phase 3 code = COMPLETE.** Vendor-intake pipeline: goldman.bills + goldman.pending_confirmations tables, Claude-vision parser, trust gate, three-write pipeline (Supabase Storage -> Drive -> Zoho Expenses), idempotency hash, failure tray, retry CLI. New env vars: GOLDMAN_DRIVE_TOKEN_B64. Live filing awaits Drive OAuth token + OPENAI_API_KEY + GOLDMAN_SUPABASE_SERVICE_KEY (the Phase 2 keys also gate this).
```

---

## Spec coverage cross-check

| Spec section | Covered by task(s) |
|---|---|
| §5.2 — `vendors.always_confirm` field | Phase 1 schema (already in place) |
| §6 — append-only bills (status/last_error) | Task 1 (bills table — supersedes_id not needed; corrections via discard/replace) |
| §7.1 — three-write order (Supabase → Drive → Zoho) | Task 12 (pipeline) |
| §7.2 — trust gate rules | Task 8 (decide_gate) |
| §7.3 — partial-write recovery | Tasks 4 (record_failure), 12 (early-return on failure), 13 (retry CLI) |
| §7.4 — Drive folder layout (`Entity / Year / Month`) | Tasks 10 (ensure_path), 13 (CLI uses invoice_date month name) |
| Bill parsing (PDF/HTML/photo) | Task 7 (Claude vision) |
| Pending confirmations (Phase 4 hook) | Tasks 2 (table), 5 (repo), 13 (CLI writes pending row) |
| Zoho Expenses API + attachment | Task 9 (ExpenseService) |
| Idempotency hash | Task 6 |
| Failure tray CLI | Task 13 (`bill list-pending` + `bill retry`) |

All Phase 3 spec requirements have at least one implementing task.

---

## What's intentionally NOT in this plan

- Gmail watcher generalization for vendor labels — covered as a follow-up in Phase 3.1 (a future small plan); Phase 3 ships the **manual** intake path so Liran can file bills via `bill file FILE`. Telegram bot (Phase 4) will route forwarded emails/photos through the same pipeline.
- Telegram inline keyboard for pending_confirmations — Phase 4.
- Vendor `typical_amount` auto-bumping per fill — handled by existing VendorRepository.bump_seen, called from Phase 4 entry points.
- pg_cron retry — Phase 6 ops; for now `bill retry` is manual.
- Drive Shared Drive support — deferred per Phase 0 decision (personal Drive only for v1).
