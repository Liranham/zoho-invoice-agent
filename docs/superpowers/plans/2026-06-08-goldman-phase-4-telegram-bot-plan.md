# Goldman Phase 4 — Telegram Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `@GoldmanCFO_bot` — Liran's primary face for Goldman. Text → tool-call agent loop with Claude → result back. Forwarded PDFs/photos route through the Phase 3 vendor-intake pipeline. Inline keyboard for `goldman.pending_confirmations` resolves trust-gate prompts. Every turn logged verbatim to `goldman.conversation_turns`. Whitelisted to Liran's chat_id only.

**Architecture:** Long-polling worker (background thread) using `python-telegram-bot v20+`. Conversation handler builds context with hybrid retrieval + the last N raw turns, passes to Claude Sonnet 4.6 with the Goldman tool registry, executes tool calls in a multi-turn loop until Claude returns plain text. Files routed to the existing `parse_bill_file` + `decide_gate` + `run_three_write_pipeline` from Phase 3 (no new code on the write path — bot just wires the input).

**Tech Stack:** Python 3.9+, **new** `python-telegram-bot>=20.0`. Existing `anthropic`, `psycopg`, `click`. Reuses Phase 0–3 modules entirely; Phase 4 is a thin orchestration layer on top.

---

## File Map

**Create:**
- `migrations/0018_bot_sessions.sql` — `goldman.bot_sessions` (per chat: current entity, last_active_at).
- `goldman_db/bot_sessions.py` — `BotSession` + repo.
- `goldman/bot/__init__.py`
- `goldman/bot/tools.py` — Goldman tool registry (definitions + execution dispatcher).
- `goldman/bot/agent.py` — multi-turn Claude tool-loop orchestrator.
- `goldman/bot/handlers.py` — Telegram message + callback handlers.
- `goldman/bot/app.py` — bot Application setup + `run_bot()`.
- `tests/test_goldman_bot_sessions_repo.py`
- `tests/test_goldman_bot_tools.py`
- `tests/test_goldman_bot_agent.py`
- `tests/test_goldman_bot_handlers.py`

**Modify:**
- `requirements.txt` — add `python-telegram-bot>=20.7`.
- `main.py` — spawn `run_bot` in a background thread when `GOLDMAN_TELEGRAM_BOT_TOKEN` is set.
- `cli.py` — add `bot run` (local dev) + `bot ping` (sanity check).
- `.env.example` — already has `GOLDMAN_TELEGRAM_BOT_TOKEN` / `_CHAT_ID`; document `GOLDMAN_BOT_ALLOWLIST_CHAT_IDS` for whitelist.

---

## Task 1: Add python-telegram-bot dependency

**Files:** Modify: `requirements.txt`

- [ ] **Step 1: Append**

```
python-telegram-bot>=20.7
```

- [ ] **Step 2: Install + verify**

```bash
python3 -m pip install --user -r requirements.txt 2>&1 | tail -3 && \
python3 -c "import telegram; print('python-telegram-bot', telegram.__version__)"
```

Expected: prints version >= 20.7. No ImportError.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt && git commit -m "Add python-telegram-bot for Goldman bot runtime

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Migration 0018 — goldman.bot_sessions

**Files:** Create: `migrations/0018_bot_sessions.sql`

Tracks per-chat state: which entity the user is currently focused on, when they were last active. One row per (chat_id × front_door).

- [ ] **Step 1: Write the SQL**

```sql
-- Goldman bot_sessions: per-chat state (current entity, last active).

CREATE TABLE IF NOT EXISTS goldman.bot_sessions (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    front_door      TEXT         NOT NULL CHECK (front_door IN ('telegram', 'claude_code')),
    chat_id         TEXT         NOT NULL,
    current_entity  TEXT,                                -- entity slug or NULL = cross-entity
    session_id      TEXT         NOT NULL,               -- rotates daily or on /reset
    last_active_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (front_door, chat_id)
);

CREATE INDEX IF NOT EXISTS idx_goldman_bot_sessions_chat
    ON goldman.bot_sessions(front_door, chat_id);
```

- [ ] **Step 2: Apply + verify**

```bash
git add migrations/0018_bot_sessions.sql && git commit -m "Add migration 0018: goldman.bot_sessions

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>" && \
python3 cli.py db migrate && \
python3 -c "
import os, psycopg
from dotenv import load_dotenv
load_dotenv()
with psycopg.connect(os.environ['GOLDMAN_DB_APP_URL']) as conn, conn.cursor() as cur:
    cur.execute('SELECT count(*) FROM goldman.bot_sessions')
    print('goldman.bot_sessions:', cur.fetchone()[0])
"
```

Expected: applied; 0 rows.

---

## Task 3: BotSessionRepository (TDD)

**Files:** Create: `goldman_db/bot_sessions.py`, `tests/test_goldman_bot_sessions_repo.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for BotSessionRepository."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman_db.bot_sessions import BotSession, BotSessionRepository


def test_get_or_create_inserts_when_missing():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    # First fetchone (SELECT) returns None; second (INSERT RETURNING) returns the new row
    new_id = uuid4()
    cur.fetchone.side_effect = [
        None,
        (new_id, "telegram", "7884172049", "amzg", "session_xyz"),
    ]

    repo = BotSessionRepository(conn)
    s = repo.get_or_create(
        front_door="telegram",
        chat_id="7884172049",
        default_entity="amzg",
        session_id="session_xyz",
    )

    assert s.id == new_id
    assert s.current_entity == "amzg"


def test_get_or_create_returns_existing_when_found():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    existing_id = uuid4()
    cur.fetchone.side_effect = [
        (existing_id, "telegram", "7884172049", "seo", "session_old"),
    ]

    repo = BotSessionRepository(conn)
    s = repo.get_or_create(
        front_door="telegram", chat_id="7884172049",
        default_entity="amzg", session_id="session_new",
    )

    assert s.id == existing_id
    assert s.current_entity == "seo"
    # Did NOT insert a second row
    insert_calls = [c for c in cur.execute.call_args_list
                    if "INSERT" in str(c)]
    assert len(insert_calls) == 0


def test_set_current_entity():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = BotSessionRepository(conn)

    repo.set_current_entity("telegram", "7884172049", "seo")

    sql = str(cur.execute.call_args)
    assert "UPDATE goldman.bot_sessions" in sql
    assert "current_entity" in sql


def test_touch_updates_last_active():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = BotSessionRepository(conn)
    repo.touch("telegram", "7884172049")

    sql = str(cur.execute.call_args)
    assert "last_active_at" in sql
```

- [ ] **Step 2: Implement**

```python
"""Repository for goldman.bot_sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class BotSession:
    id: UUID
    front_door: str
    chat_id: str
    current_entity: Optional[str]
    session_id: str


_COLS = "id, front_door, chat_id, current_entity, session_id"


def _row(r) -> BotSession:
    return BotSession(
        id=r[0], front_door=r[1], chat_id=r[2],
        current_entity=r[3], session_id=r[4],
    )


class BotSessionRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def get_or_create(
        self, *, front_door: str, chat_id: str,
        default_entity: Optional[str], session_id: str,
    ) -> BotSession:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.bot_sessions "
                f"WHERE front_door = %s AND chat_id = %s",
                (front_door, chat_id),
            )
            row = cur.fetchone()
            if row:
                return _row(row)

            cur.execute(
                f"""
                INSERT INTO goldman.bot_sessions
                    (front_door, chat_id, current_entity, session_id)
                VALUES (%s, %s, %s, %s)
                RETURNING {_COLS}
                """,
                (front_door, chat_id, default_entity, session_id),
            )
            return _row(cur.fetchone())

    def set_current_entity(self, front_door: str, chat_id: str,
                            entity_slug: Optional[str]) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.bot_sessions
                SET current_entity = %s, last_active_at = now()
                WHERE front_door = %s AND chat_id = %s
                """,
                (entity_slug, front_door, chat_id),
            )

    def touch(self, front_door: str, chat_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.bot_sessions
                SET last_active_at = now()
                WHERE front_door = %s AND chat_id = %s
                """,
                (front_door, chat_id),
            )
```

- [ ] **Step 3: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_bot_sessions_repo.py -v 2>&1 | tail -7 && \
git add goldman_db/bot_sessions.py tests/test_goldman_bot_sessions_repo.py && \
git commit -m "Add BotSessionRepository (per-chat current_entity + session_id)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 4 tests pass.

---

## Task 4: Goldman tool registry (TDD)

**Files:** Create: `goldman/bot/__init__.py`, `goldman/bot/tools.py`, `tests/test_goldman_bot_tools.py`

The registry defines tool schemas Claude sees + a dispatcher that executes them.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the Goldman tool registry."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from goldman.bot.tools import TOOL_SCHEMAS, execute_tool


def test_tool_schemas_have_expected_names():
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert "recall" in names
    assert "who" in names
    assert "remember_fact" in names
    assert "list_invoices" in names
    assert "list_pending_confirmations" in names


def test_execute_recall_runs_hybrid_search():
    ctx = MagicMock()
    ctx.entity_slug = "amzg"
    ctx.embedder.embed_batch.return_value = [[0.1] * 1536]
    ctx.conn = MagicMock()
    # patch the hybrid_search call
    fake_results = [MagicMock(source_type="fact", source_id=uuid4(),
                              excerpt="hello", score=0.5, entity_id=None,
                              metadata={})]
    from unittest.mock import patch
    with patch("goldman.bot.tools.hybrid_search", return_value=fake_results):
        result = execute_tool(
            ctx=ctx, name="recall",
            arguments={"question": "what about VAT?"},
        )
    assert "hello" in result or "results" in result or "fact" in result


def test_execute_unknown_tool_raises():
    ctx = MagicMock()
    with pytest.raises(ValueError, match="Unknown tool"):
        execute_tool(ctx=ctx, name="not_a_tool", arguments={})
```

- [ ] **Step 2: Implement**

Create `goldman/bot/__init__.py`:

```python
"""Goldman Telegram bot."""
```

Create `goldman/bot/tools.py`:

```python
"""Goldman tool registry.

TOOL_SCHEMAS define what Claude can call. execute_tool dispatches and
returns a text result Claude can read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from goldman_db.hybrid_search import hybrid_search


TOOL_SCHEMAS = [
    {
        "name": "recall",
        "description": "Search Goldman's memory (facts, conversations, documents) for relevant context. Use when the user asks about prior decisions, advice, or document content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The query in natural language."},
                "top_n": {"type": "integer", "default": 8},
            },
            "required": ["question"],
        },
    },
    {
        "name": "who",
        "description": "Print Goldman's company brain: every entity with tax registrations, bank accounts, top clients/vendors. Use when the user asks about the company structure.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "remember_fact",
        "description": "Record a structured fact about an entity (target/preference/constraint/commitment/event/decision/note).",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["target", "preference", "constraint",
                             "commitment", "event", "decision", "note"],
                },
                "text": {"type": "string"},
            },
            "required": ["kind", "text"],
        },
    },
    {
        "name": "list_invoices",
        "description": "List recent client invoices for the current entity in Zoho Books.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string",
                            "enum": ["draft", "sent", "paid", "overdue"]},
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "list_pending_confirmations",
        "description": "List bills waiting for the user's confirmation.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "switch_entity",
        "description": "Change the user's current focus to another entity (amzg/seo).",
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
    },
]


@dataclass
class ToolContext:
    """Everything an executed tool needs."""
    conn: object
    entity_slug: Optional[str]
    chat_id: str
    embedder: object   # EmbeddingClient or None
    bot_session_repo: object


def execute_tool(*, ctx: ToolContext, name: str, arguments: dict) -> str:
    """Run the tool and return a text summary Claude can read."""
    if name == "recall":
        return _recall(ctx, arguments)
    if name == "who":
        return _who(ctx)
    if name == "remember_fact":
        return _remember_fact(ctx, arguments)
    if name == "list_invoices":
        return _list_invoices(ctx, arguments)
    if name == "list_pending_confirmations":
        return _list_pending(ctx)
    if name == "switch_entity":
        return _switch_entity(ctx, arguments)
    raise ValueError(f"Unknown tool: {name}")


def _recall(ctx, args) -> str:
    question = args["question"]
    top_n = int(args.get("top_n", 8))
    if ctx.embedder is None:
        return "Recall unavailable: OPENAI_API_KEY not configured."
    vec = ctx.embedder.embed_batch([question])[0]
    from goldman_db.entities import EntityRepository
    entity_id = None
    if ctx.entity_slug:
        ent = EntityRepository(ctx.conn).get_by_slug(ctx.entity_slug)
        if ent:
            entity_id = ent.id
    results = hybrid_search(
        ctx.conn, query_embedding=vec, query_text=question,
        entity_id=entity_id, top_n=top_n,
    )
    if not results:
        return f"No memory entries match: {question!r}."
    lines = [f"Top {len(results)} matches:"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. [{r.source_type}] score={r.score:.3f} :: {r.excerpt[:200]}")
    return "\n".join(lines)


def _who(ctx) -> str:
    from goldman.who import build_who_view, render_who
    from goldman_db.bank_accounts import BankAccountRepository
    from goldman_db.clients import ClientRepository
    from goldman_db.entities import EntityRepository
    from goldman_db.tax_registrations import TaxRegistrationRepository
    from goldman_db.vendors import VendorRepository

    summaries = build_who_view(
        entities_repo=EntityRepository(ctx.conn),
        tax_repo=TaxRegistrationRepository(ctx.conn),
        bank_repo=BankAccountRepository(ctx.conn),
        clients_repo=ClientRepository(ctx.conn),
        vendors_repo=VendorRepository(ctx.conn),
    )
    return render_who(summaries)


def _remember_fact(ctx, args) -> str:
    from goldman_db.entities import EntityRepository
    from goldman_db.facts import FactRepository

    entity_id = None
    if ctx.entity_slug:
        ent = EntityRepository(ctx.conn).get_by_slug(ctx.entity_slug)
        entity_id = ent.id if ent else None

    new_id = FactRepository(ctx.conn).upsert(
        entity_id=entity_id,
        kind=args["kind"], fact=args["text"],
        source="user_explicit",
    )
    return f"Stored fact {new_id} (kind={args['kind']})."


def _list_invoices(ctx, args) -> str:
    if not ctx.entity_slug:
        return "Tell me which entity (amzg or seo) before listing invoices."
    from goldman.zoho import invoice_service_for
    from goldman_db.entities import EntityRepository

    svc = invoice_service_for(
        ctx.entity_slug, entity_repo=EntityRepository(ctx.conn),
    )
    status = args.get("status", "")
    invoices = svc.list_invoices(status=status)
    invoices = invoices[: int(args.get("limit", 10))]
    if not invoices:
        return "No invoices found."
    lines = []
    for inv in invoices:
        lines.append(
            f"{inv.invoice_number} | {inv.status} | {inv.date} | "
            f"{inv.total:.2f} {inv.currency_code} | {inv.customer_name}"
        )
    return "\n".join(lines)


def _list_pending(ctx) -> str:
    from goldman_db.pending_confirmations import PendingConfirmationRepository
    rows = PendingConfirmationRepository(ctx.conn).list_open(limit=20)
    if not rows:
        return "No pending confirmations."
    return "\n".join(f"- {r.prompt}" for r in rows)


def _switch_entity(ctx, args) -> str:
    slug = args["slug"].lower()
    from goldman_db.entities import EntityRepository
    ent = EntityRepository(ctx.conn).get_by_slug(slug)
    if not ent:
        return f"Unknown entity slug: {slug}."
    ctx.bot_session_repo.set_current_entity(
        "telegram", ctx.chat_id, slug,
    )
    ctx.entity_slug = slug
    return f"Switched to {ent.legal_name} ({slug})."
```

- [ ] **Step 3: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_bot_tools.py -v 2>&1 | tail -7 && \
git add goldman/bot/__init__.py goldman/bot/tools.py tests/test_goldman_bot_tools.py && \
git commit -m "Add Goldman tool registry (recall/who/remember/list_invoices/...)

Tools route to Phase 0-3 modules; ToolContext carries entity_slug, conn,
embedder, session repo. execute_tool returns plain-text result for Claude.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 3 tests pass.

---

## Task 5: Conversation agent loop (TDD)

**Files:** Create: `goldman/bot/agent.py`, `tests/test_goldman_bot_agent.py`

The agent loop: Claude responds either with text or tool_use blocks. If tool_use, execute → tool_result → continue loop. Cap iterations to prevent runaway.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the agent loop."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from goldman.bot.agent import run_agent


def test_agent_returns_text_when_no_tool_use():
    fake_claude = MagicMock()
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Hello from Goldman."
    resp = MagicMock()
    resp.content = [text_block]
    resp.stop_reason = "end_turn"
    fake_claude.messages.create.return_value = resp

    ctx = MagicMock()
    result = run_agent(
        claude=fake_claude, model="claude-sonnet-4-6",
        system="You are Goldman.", messages=[],
        ctx=ctx, max_iterations=3,
    )
    assert result == "Hello from Goldman."


def test_agent_executes_tool_then_returns_followup_text():
    fake_claude = MagicMock()
    # First response: tool_use
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = "tool_1"
    tool_block.name = "who"
    tool_block.input = {}
    first_resp = MagicMock()
    first_resp.content = [tool_block]
    first_resp.stop_reason = "tool_use"

    # Second response: text follow-up
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Your company structure is..."
    second_resp = MagicMock()
    second_resp.content = [text_block]
    second_resp.stop_reason = "end_turn"

    fake_claude.messages.create.side_effect = [first_resp, second_resp]

    with patch("goldman.bot.agent.execute_tool", return_value="AMZ Expert Global..."):
        result = run_agent(
            claude=fake_claude, model="claude-sonnet-4-6",
            system="You are Goldman.", messages=[],
            ctx=MagicMock(), max_iterations=3,
        )

    assert result == "Your company structure is..."
    assert fake_claude.messages.create.call_count == 2
```

- [ ] **Step 2: Implement**

```python
"""Multi-turn Claude tool-loop for the Goldman bot."""

from __future__ import annotations

from typing import Optional

from goldman.bot.tools import TOOL_SCHEMAS, execute_tool


def run_agent(
    *,
    claude,
    model: str,
    system: str,
    messages: list,
    ctx,
    max_iterations: int = 5,
    max_tokens: int = 2048,
) -> str:
    """Run a tool-using conversation until Claude returns plain text.

    messages is the running conversation (assistant + user blocks).
    Returns the final assistant text. Caller appends both directions to
    their own log.
    """
    working = list(messages)

    for _ in range(max_iterations):
        resp = claude.messages.create(
            model=model, max_tokens=max_tokens,
            system=system, messages=working,
            tools=TOOL_SCHEMAS,
        )

        # Did Claude finish with text?
        if resp.stop_reason != "tool_use":
            for block in resp.content:
                if getattr(block, "type", None) == "text":
                    return block.text
            return ""

        # Tool use — append Claude's request, execute, append tool_result,
        # loop again.
        working.append({
            "role": "assistant",
            "content": [
                {"type": b.type,
                 **({"text": b.text} if b.type == "text" else {}),
                 **({"id": b.id, "name": b.name, "input": b.input}
                    if b.type == "tool_use" else {})}
                for b in resp.content
            ],
        })

        tool_results = []
        for b in resp.content:
            if getattr(b, "type", None) != "tool_use":
                continue
            try:
                result_text = execute_tool(
                    ctx=ctx, name=b.name, arguments=dict(b.input),
                )
            except Exception as e:
                result_text = f"Tool error: {e}"
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": b.id,
                "content": result_text,
            })

        working.append({"role": "user", "content": tool_results})

    return "(Goldman: hit the tool-iteration cap; please try again.)"
```

- [ ] **Step 3: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_bot_agent.py -v 2>&1 | tail -6 && \
git add goldman/bot/agent.py tests/test_goldman_bot_agent.py && \
git commit -m "Add agent loop (Claude tool-use multi-turn orchestrator)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 2 tests pass.

---

## Task 6: Telegram message + callback handlers (TDD)

**Files:** Create: `goldman/bot/handlers.py`, `tests/test_goldman_bot_handlers.py`

Handlers are framework-thin: parse the update, build context, call the agent, send reply, log turns.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the Telegram handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from goldman.bot.handlers import is_allowed_chat


def test_is_allowed_chat_matches_whitelist(monkeypatch):
    monkeypatch.setenv("GOLDMAN_BOT_ALLOWLIST_CHAT_IDS", "7884172049,12345")

    assert is_allowed_chat(7884172049) is True
    assert is_allowed_chat(12345) is True
    assert is_allowed_chat(99999) is False


def test_is_allowed_chat_denies_when_empty_allowlist(monkeypatch):
    monkeypatch.delenv("GOLDMAN_BOT_ALLOWLIST_CHAT_IDS", raising=False)
    assert is_allowed_chat(7884172049) is False
```

- [ ] **Step 2: Implement**

```python
"""Telegram message + callback handlers for the Goldman bot."""

from __future__ import annotations

import logging
import os
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from goldman.bot.agent import run_agent
from goldman.bot.tools import ToolContext
from goldman.llm import GoldmanLLM
from goldman_db.bot_sessions import BotSessionRepository
from goldman_db.connection import app_conn
from goldman_db.conversation_turns import ConversationTurnRepository
from goldman_db.entities import EntityRepository
from goldman_db.pending_confirmations import PendingConfirmationRepository

logger = logging.getLogger(__name__)


GOLDMAN_PERSONA = """\
You are Goldman, the CFO of AMZ Expert Global Limited (Hong Kong parent)
and Specific Edge Outsourcing LLC (US subsidiary). You speak in clear
plain English, no jargon. You are conservative, precise, and never
fabricate. When you don't know, you say so. When you act, you cite the
source (which Zoho org, which document, which prior conversation).

You have tools to recall memory, look up the company structure,
list invoices, and remember facts. Use them.
You NEVER move money, file taxes, sign contracts, or delete data.
You prepare, draft, recommend, and alert; the user executes.
"""


def is_allowed_chat(chat_id: int) -> bool:
    raw = os.getenv("GOLDMAN_BOT_ALLOWLIST_CHAT_IDS", "")
    if not raw:
        return False
    allowed = {int(x.strip()) for x in raw.split(",") if x.strip()}
    return chat_id in allowed


def _session_id_for_today(chat_id: int) -> str:
    from datetime import datetime
    return f"tg-{chat_id}-{datetime.utcnow().strftime('%Y%m%d')}"


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not is_allowed_chat(chat_id):
        logger.warning("Denied chat: %s", chat_id)
        return

    user_text = update.message.text or ""
    session_id = _session_id_for_today(chat_id)

    # Build context
    embedder = None
    try:
        from goldman.embeddings import EmbeddingClient
        embedder = EmbeddingClient()
    except Exception:
        embedder = None    # OK; recall tool will say "unavailable"

    llm = GoldmanLLM()

    with app_conn() as conn:
        bot_sessions = BotSessionRepository(conn)
        sess = bot_sessions.get_or_create(
            front_door="telegram",
            chat_id=str(chat_id),
            default_entity="amzg",
            session_id=session_id,
        )
        entity_slug = sess.current_entity or "amzg"

        # Log user turn
        turns = ConversationTurnRepository(conn)
        entity_id = None
        ent = EntityRepository(conn).get_by_slug(entity_slug) if entity_slug else None
        if ent:
            entity_id = ent.id
        turns.insert(
            entity_id=entity_id, session_id=sess.session_id,
            front_door="telegram", role="user", text=user_text,
        )

        # Build last N turns as messages
        recent = turns.list_by_session(sess.session_id)[-10:]
        messages = []
        for t in recent:
            if t.role == "user":
                messages.append({"role": "user", "content": t.text})
            elif t.role == "assistant":
                messages.append({"role": "assistant", "content": t.text})

        ctx = ToolContext(
            conn=conn, entity_slug=entity_slug,
            chat_id=str(chat_id), embedder=embedder,
            bot_session_repo=bot_sessions,
        )

        reply = run_agent(
            claude=llm._client, model=llm.model,
            system=GOLDMAN_PERSONA, messages=messages, ctx=ctx,
        )

        # Log assistant turn
        turns.insert(
            entity_id=entity_id, session_id=sess.session_id,
            front_door="telegram", role="assistant", text=reply,
        )
        bot_sessions.touch("telegram", str(chat_id))

    await update.message.reply_text(reply or "(empty reply)")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A forwarded PDF / photo — route through Phase 3 vendor intake."""
    chat_id = update.effective_chat.id
    if not is_allowed_chat(chat_id):
        return

    msg = update.message
    doc = msg.document or (msg.photo[-1] if msg.photo else None)
    if not doc:
        await msg.reply_text("Send me a PDF or photo of a bill.")
        return

    file_obj = await context.bot.get_file(doc.file_id)
    import tempfile
    import os as _os
    suffix = _os.path.splitext(getattr(doc, "file_name", "") or ".pdf")[1] or ".pdf"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    await file_obj.download_to_drive(tmp.name)

    from goldman.bills.parser import parse_bill_file
    from goldman.bills.idempotency import bill_hash
    from goldman_db.bills import BillRepository, DuplicateBillError
    from goldman_db.vendors import VendorRepository
    from goldman.bills.trust_gate import decide_gate

    llm = GoldmanLLM()
    with app_conn() as conn:
        entities = EntityRepository(conn).list_all()
    known = [e.legal_name for e in entities]
    parse = parse_bill_file(__import__("pathlib").Path(tmp.name),
                             llm=llm, known_entities=known)

    # Resolve entity from parse
    entity_slug = None
    for e in entities:
        if parse.billing_entity and \
           e.legal_name.strip().lower() == parse.billing_entity.strip().lower():
            entity_slug = e.slug
            break

    if not entity_slug:
        await msg.reply_text(
            f"I parsed: {parse.vendor} {parse.amount} {parse.currency}\n"
            f"But I can't tell which company is being billed. "
            f"Reply with 'amzg' or 'seo'."
        )
        return

    with app_conn() as conn:
        ent = EntityRepository(conn).get_by_slug(entity_slug)
        vendors_repo = VendorRepository(conn)
        bills_repo = BillRepository(conn)
        pending = PendingConfirmationRepository(conn)

        from goldman.bills.idempotency import normalise_vendor
        vendors = vendors_repo.list_by_entity(ent.id)
        vendor = next(
            (v for v in vendors
             if normalise_vendor(v.vendor_name) == normalise_vendor(parse.vendor)),
            None,
        )

        h = bill_hash(
            vendor=parse.vendor, invoice_number=parse.invoice_number,
            amount=parse.amount, invoice_date=parse.invoice_date,
        )
        existing = bills_repo.get_by_idempotency_hash(h)
        if existing:
            await msg.reply_text(f"Already filed (bill {existing.id}).")
            return

        try:
            bill_id = bills_repo.insert(
                entity_id=ent.id,
                vendor_id=vendor.id if vendor else None,
                vendor_name_at_intake=parse.vendor,
                invoice_number=parse.invoice_number,
                invoice_date=parse.invoice_date,
                amount=parse.amount, currency=parse.currency,
                idempotency_hash=h,
                line_items=parse.line_items,
                tax_amount=parse.tax_amount,
                original_filename=getattr(doc, "file_name", None),
            )
        except DuplicateBillError:
            await msg.reply_text("Race: duplicate found on insert; skipping.")
            return

        decision = decide_gate(
            parse=parse, vendor=vendor,
            known_entity_slug=entity_slug, bill_already_filed=False,
        )
        if not decision.auto_file:
            bills_repo.mark_confirmation_required(bill_id, reason=decision.reason)
            pending.insert(
                bill_id=bill_id, entity_id=ent.id,
                prompt=(
                    f"{parse.vendor} {parse.amount} {parse.currency} -> "
                    f"{ent.legal_name}? Reason: {decision.reason}"
                ),
                options=[
                    {"label": "Yes, file", "value": f"file:{bill_id}"},
                    {"label": "Hold", "value": f"hold:{bill_id}"},
                    {"label": "Discard", "value": f"discard:{bill_id}"},
                ],
            )

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Yes, file", callback_data=f"file:{bill_id}"),
                 InlineKeyboardButton("Hold", callback_data=f"hold:{bill_id}"),
                 InlineKeyboardButton("Discard", callback_data=f"discard:{bill_id}")],
            ])
            await msg.reply_text(
                f"{parse.vendor} {parse.amount} {parse.currency} -> {ent.legal_name}\n"
                f"Reason to confirm: {decision.reason}",
                reply_markup=kb,
            )
            return

    # Auto-file path: kick off pipeline (synchronous; user waits ~10s)
    await msg.reply_text("Trust-gate cleared — filing now...")
    # NOTE: live three-write pipeline requires GOLDMAN_DRIVE_TOKEN_B64 +
    # GOLDMAN_SUPABASE_SERVICE_KEY. CLI 'bill file' uses the same code path.
    await msg.reply_text(
        "(Auto-file from Telegram pending Drive token. "
        "Use 'cli.py bill file' meanwhile.)"
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inline-keyboard button press."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    if not is_allowed_chat(chat_id):
        return

    data = query.data or ""
    if ":" not in data:
        return
    action, bill_id_str = data.split(":", 1)

    from uuid import UUID
    bill_id = UUID(bill_id_str)

    with app_conn() as conn:
        bills_repo = __import__("goldman_db.bills", fromlist=["BillRepository"]).BillRepository(conn)
        pending = PendingConfirmationRepository(conn)
        opens = pending.list_open(limit=100)
        matching = next((p for p in opens if p.bill_id == bill_id), None)
        if matching:
            pending.record_answer(matching.id, answer=action)
        if action == "discard":
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE goldman.bills SET status = 'discarded' WHERE id = %s",
                    (bill_id,),
                )

    await query.edit_message_text(f"Recorded: {action}")
```

- [ ] **Step 3: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_bot_handlers.py -v 2>&1 | tail -5 && \
git add goldman/bot/handlers.py tests/test_goldman_bot_handlers.py && \
git commit -m "Add bot handlers (text, document, callback)

Whitelist guard via GOLDMAN_BOT_ALLOWLIST_CHAT_IDS. Text routes through
the agent loop. Document upload routes through Phase 3 vendor intake.
Callback resolves pending_confirmations via inline keyboard.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 2 tests pass.

---

## Task 7: Bot Application + run_bot

**Files:** Create: `goldman/bot/app.py`

- [ ] **Step 1: Implement**

```python
"""Goldman Telegram bot Application setup."""

from __future__ import annotations

import logging
import os

from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters,
)

from goldman.bot.handlers import handle_text, handle_document, handle_callback

logger = logging.getLogger(__name__)


async def _start(update, context):
    await update.message.reply_text(
        "Goldman here. CFO of AMZ Expert Global Limited.\n"
        "Send me a bill (PDF/photo), ask a question, or type 'who' to see "
        "the company brain."
    )


def run_bot():
    """Start the bot (blocking)."""
    token = os.getenv("GOLDMAN_TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("GOLDMAN_TELEGRAM_BOT_TOKEN not set.")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", _start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Goldman bot starting — long-polling...")
    app.run_polling(allowed_updates=["message", "callback_query"])
```

- [ ] **Step 2: Verify import works**

```bash
python3 -c "from goldman.bot.app import run_bot; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add goldman/bot/app.py && git commit -m "Add bot Application (run_bot — long-polling)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: CLI — `bot run` + `bot ping`

**Files:** Modify: `cli.py`

- [ ] **Step 1: Add the bot group**

In `cli.py`, after the `bill` group, add:

```python
# -----------------------------------------------------------------------------
# Bot (Phase 4)
# -----------------------------------------------------------------------------

@cli.group("bot")
def bot_group():
    """Goldman Telegram bot operations."""


@bot_group.command("run")
def bot_run_cmd():
    """Start the Goldman Telegram bot (long-polling, blocking)."""
    from goldman.bot.app import run_bot
    run_bot()


@bot_group.command("ping")
def bot_ping_cmd():
    """Send a test ping via the bot token (no polling)."""
    import os
    import requests
    token = os.getenv("GOLDMAN_TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("GOLDMAN_TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise click.ClickException(
            "GOLDMAN_TELEGRAM_BOT_TOKEN and GOLDMAN_TELEGRAM_CHAT_ID required."
        )
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": "Goldman bot ping ✓"},
    )
    if r.ok:
        click.echo(f"  ok: {r.json().get('result', {}).get('message_id')}")
    else:
        click.echo(f"  failed: {r.status_code} {r.text}")
```

- [ ] **Step 2: Verify**

```bash
python3 -c "import cli; print('OK')" && python3 cli.py bot --help 2>&1 | tail -6
```

Expected: `OK` + bot subcommands listed.

- [ ] **Step 3: Commit**

```bash
git add cli.py && git commit -m "CLI: add 'bot run' + 'bot ping' commands

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: Wire bot into main.py server mode

**Files:** Modify: `main.py`

When `cmd_server` starts on Render and `GOLDMAN_TELEGRAM_BOT_TOKEN` is set, spawn the bot in a thread alongside the existing health server.

- [ ] **Step 1: Add bot spawn block**

In `main.py`, inside `cmd_server`, after the existing `_invoice_services` population and BEFORE the `threading.Event().wait()` final block, add:

```python
        # Goldman Telegram bot (Phase 4)
        if os.environ.get("GOLDMAN_TELEGRAM_BOT_TOKEN"):
            try:
                from goldman.bot.app import run_bot
                threading.Thread(
                    target=run_bot, daemon=True, name="goldman-bot",
                ).start()
                logger.info("Goldman bot thread started")
            except Exception as e:
                logger.exception("Goldman bot failed to start: %s", e)
```

- [ ] **Step 2: Verify**

```bash
python3 -c "import main; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add main.py && git commit -m "main.py: spawn Goldman bot thread in cmd_server

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: Update .env.example with bot whitelist

**Files:** Modify: `.env.example`

- [ ] **Step 1: Append**

Open `.env.example` and append:

```bash

# ============================================================================
# Goldman Phase 4 — Telegram bot
# ============================================================================
# Bot token (created in Phase 0): GOLDMAN_TELEGRAM_BOT_TOKEN already set above.
# Comma-separated chat ids that may talk to Goldman. Everyone else is ignored.
GOLDMAN_BOT_ALLOWLIST_CHAT_IDS=7884172049
```

- [ ] **Step 2: Commit**

```bash
git add .env.example && git commit -m "Document Phase 4 bot allowlist env var

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 11: Final regression + acceptance

**Files:** (no code changes)

- [ ] **Step 1: Full test sweep**

```bash
cd ~/Desktop/Obsidian/Projects/zoho-invoice-agent && python3 -m pytest 2>&1 | tail -3
```

Expected: every test passes (Phase 0/1/2/3's 145 + Phase 4's new ≈ 155).

- [ ] **Step 2: CLI surface check**

```bash
python3 cli.py bot --help 2>&1 | tail -6
```

Expected: `run` and `ping` subcommands.

- [ ] **Step 3: Bot ping (live)**

If `GOLDMAN_TELEGRAM_BOT_TOKEN` + `GOLDMAN_TELEGRAM_CHAT_ID` are set (they are from Phase 0):

```bash
python3 cli.py bot ping
```

Expected: `ok: <message_id>` AND the message appears in your Telegram chat.

- [ ] **Step 4: Append memory**

Append to `~/.claude/projects/-Users-hamburg/memory/project_goldman.md` (under Status):

```markdown
- **Phase 4 code = COMPLETE.** Bot tables: goldman.bot_sessions. Modules: goldman.bot.{tools, agent, handlers, app}. Tool registry: recall, who, remember_fact, list_invoices, list_pending_confirmations, switch_entity. Agent loop = multi-turn Claude tool-use orchestrator capped at 5 iterations. Text → agent → reply, with last 10 conversation_turns as context. Document/photo upload → Phase 3 vendor intake → inline keyboard for trust-gate confirms. Whitelist via GOLDMAN_BOT_ALLOWLIST_CHAT_IDS. CLI: `bot run` (long-polling), `bot ping` (test). main.py spawns the bot thread when GOLDMAN_TELEGRAM_BOT_TOKEN is set.
```

---

## Spec coverage cross-check

| Spec section | Covered by task(s) |
|---|---|
| §8.1 — @GoldmanCFO_bot separate from Bob | Task 7 (uses GOLDMAN_TELEGRAM_BOT_TOKEN) |
| §8.1 — conversation router | Task 5 (agent), 6 (handlers) |
| §8.1 — tool registry | Task 4 |
| §8.1 — every turn logged to conversation_turns | Task 6 (handle_text logs both directions) |
| §8.1 — file/photo upload → intake | Task 6 (handle_document) |
| §8.1 — proactive trust-gate confirmations | Tasks 6 (inline keyboard for parsed bills) |
| §8.1 — Render deployment | Task 9 (spawn thread in cmd_server) |
| Bot allowlist | Task 6 (is_allowed_chat) |

---

## What's intentionally NOT in this plan

- Inline-keyboard "switch entity" buttons — user types it (handled by `switch_entity` tool).
- Conversational embedding-pending — embeddings are CLI-driven for v1; Phase 6 can move to cron.
- Auto-file from Telegram (full three-write inside the bot handler) — handler defers to CLI for now because the live pipeline needs Drive + Storage keys which won't be on Render until they're configured. Once keys land, Task 9.1 (future small follow-up) wires the full pipeline directly into `handle_document`.
- Multi-user / team — bot is single-user (Liran).
- Voice notes — Phase 6.
