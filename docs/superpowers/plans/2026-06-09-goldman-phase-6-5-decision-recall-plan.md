# Goldman Phase 6.5 — Decision Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class "what did we decide about X" query that returns a chronological timeline of decision-kind facts matching a topic. Surfaces through the bot, the API, and the Claude Code plugin.

**Architecture:** One new pure function (`goldman/decisions.py::decision_timeline`) backed by a simple SQL query against `goldman.facts_live`. Three thin wrappers around it: a bot tool, an API endpoint, and a plugin slash command. The bot's persona is taught one sentence about when to use the new tool.

**Tech Stack:** Python 3.9, existing `psycopg`, `pytest`. No new dependencies. No schema changes.

---

## File Map

**Create:**
- `goldman/decisions.py` — `decision_timeline(conn, topic, entity_slug=None, limit=20)`.
- `tests/test_goldman_decisions.py` — 3 unit tests.
- `goldman.plugin/commands/decisions.md` — `/goldman:decisions <topic>` slash command.

**Modify:**
- `goldman/bot/tools.py` — register `recall_decisions` in `TOOL_SCHEMAS` + add dispatcher case + helper.
- `tests/test_goldman_bot_tools.py` — extend with 2 tests.
- `goldman/bot/handlers.py` — append one sentence to `GOLDMAN_PERSONA`.
- `tests/test_goldman_bot_handlers.py` — 1 new test for the persona sentence.
- `goldman/api/endpoints.py` — add `handle_decisions`.
- `tests/test_goldman_api_endpoints.py` — 2 new tests.
- `main.py` — wire `POST /v1/decisions` into `_handle_api`.

---

## Task 1: `goldman/decisions.py` — `decision_timeline` (TDD)

**Files:**
- Create: `goldman/decisions.py`
- Create: `tests/test_goldman_decisions.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_goldman_decisions.py`:

```python
"""Tests for decision_timeline."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from goldman.decisions import decision_timeline


def test_decision_timeline_returns_list_with_entity_slug_joined():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    fid1, fid2 = uuid4(), uuid4()
    eid = uuid4()
    cur.fetchall.return_value = [
        (fid1, "Hire UK accountant for VAT filings", "amzg", eid,
         datetime(2026, 6, 8, tzinfo=timezone.utc), None),
        (fid2, "Defer UK VAT registration until threshold", "amzg", eid,
         datetime(2026, 5, 14, tzinfo=timezone.utc), None),
    ]

    result = decision_timeline(conn=conn, topic="VAT")

    assert len(result) == 2
    assert result[0]["fact"] == "Hire UK accountant for VAT filings"
    assert result[0]["entity_slug"] == "amzg"
    assert result[0]["id"] == fid1
    assert result[0]["supersedes_id"] is None
    assert result[1]["fact"] == "Defer UK VAT registration until threshold"
    sql = str(cur.execute.call_args)
    assert "facts_live" in sql
    assert "kind = 'decision'" in sql or "kind='decision'" in sql
    assert "ORDER BY" in sql.upper()


def test_decision_timeline_returns_empty_when_no_match():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    result = decision_timeline(conn=conn, topic="nothing matches")

    assert result == []


def test_decision_timeline_raises_for_empty_topic():
    conn = MagicMock()

    with pytest.raises(ValueError, match="topic"):
        decision_timeline(conn=conn, topic="   ")
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd ~/Desktop/Obsidian/Projects/zoho-invoice-agent && \
python3 -m pytest tests/test_goldman_decisions.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'goldman.decisions'`.

- [ ] **Step 3: Implement**

Create `goldman/decisions.py`:

```python
"""Decision recall primitive (Phase 6.5).

Pure function backed by SQL against goldman.facts_live. Returns a
chronological list of decision-kind facts matching the topic.
"""

from __future__ import annotations

from typing import Optional


def decision_timeline(
    *,
    conn,
    topic: str,
    entity_slug: Optional[str] = None,
    limit: int = 20,
) -> list:
    """Return decision facts whose text matches `topic` (case-insensitive
    substring), most recent first.

    When entity_slug is provided, restricts to that entity OR cross-entity
    facts (entity_id IS NULL).
    """
    if not topic or not topic.strip():
        raise ValueError("topic must be a non-empty string")

    with conn.cursor() as cur:
        if entity_slug is None:
            cur.execute(
                """
                SELECT f.id, f.fact, e.slug AS entity_slug, f.entity_id,
                       f.created_at, f.supersedes_id
                FROM goldman.facts_live f
                LEFT JOIN goldman.entities e ON e.id = f.entity_id
                WHERE f.kind = 'decision'
                  AND f.fact ILIKE '%%' || %s || '%%'
                ORDER BY f.created_at DESC
                LIMIT %s
                """,
                (topic, limit),
            )
        else:
            cur.execute(
                """
                SELECT f.id, f.fact, e.slug AS entity_slug, f.entity_id,
                       f.created_at, f.supersedes_id
                FROM goldman.facts_live f
                LEFT JOIN goldman.entities e ON e.id = f.entity_id
                WHERE f.kind = 'decision'
                  AND f.fact ILIKE '%%' || %s || '%%'
                  AND (e.slug = %s OR f.entity_id IS NULL)
                ORDER BY f.created_at DESC
                LIMIT %s
                """,
                (topic, entity_slug, limit),
            )
        rows = cur.fetchall()

    return [
        {
            "id": r[0],
            "fact": r[1],
            "entity_slug": r[2],
            "created_at": r[4].isoformat() if r[4] else None,
            "supersedes_id": r[5],
        }
        for r in rows
    ]
```

- [ ] **Step 4: Run — should pass**

```bash
python3 -m pytest tests/test_goldman_decisions.py -v 2>&1 | tail -8
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add goldman/decisions.py tests/test_goldman_decisions.py && \
git commit -m "Add decision_timeline primitive (Phase 6.5 part 1)

Pure function: queries goldman.facts_live JOIN entities WHERE kind=
'decision' AND fact ILIKE topic, ORDER BY created_at DESC. Returns list
of {id, fact, entity_slug, created_at, supersedes_id}. Raises
ValueError for empty topic.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Bot tool `recall_decisions` (TDD)

**Files:**
- Modify: `goldman/bot/tools.py`
- Modify: `tests/test_goldman_bot_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_goldman_bot_tools.py`:

```python
def test_recall_decisions_is_in_tool_schemas():
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert "recall_decisions" in names
    schema = next(t for t in TOOL_SCHEMAS if t["name"] == "recall_decisions")
    assert "topic" in schema["input_schema"]["properties"]


def test_execute_recall_decisions_returns_formatted_timeline():
    ctx = MagicMock()
    ctx.entity_slug = "amzg"
    ctx.conn = MagicMock()
    fake_results = [
        {"id": uuid4(),
         "fact": "Hire UK accountant for VAT filings",
         "entity_slug": "amzg",
         "created_at": "2026-06-08T00:00:00+00:00",
         "supersedes_id": None},
    ]
    from unittest.mock import patch
    with patch("goldman.bot.tools.decision_timeline", return_value=fake_results):
        result = execute_tool(
            ctx=ctx, name="recall_decisions",
            arguments={"topic": "VAT"},
        )
    assert "VAT" in result or "Decision timeline" in result
    assert "Hire UK accountant" in result
    assert "2026-06-08" in result
    assert "amzg" in result


def test_execute_recall_decisions_empty_results_returns_no_matches_message():
    ctx = MagicMock()
    ctx.entity_slug = "amzg"
    ctx.conn = MagicMock()
    from unittest.mock import patch
    with patch("goldman.bot.tools.decision_timeline", return_value=[]):
        result = execute_tool(
            ctx=ctx, name="recall_decisions",
            arguments={"topic": "nothing"},
        )
    assert "No prior decisions" in result or "no decisions" in result.lower()
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_bot_tools.py::test_recall_decisions_is_in_tool_schemas -v 2>&1 | tail -5
```

Expected: AssertionError (tool not in TOOL_SCHEMAS yet).

- [ ] **Step 3: Implement**

Open `goldman/bot/tools.py`. Find the existing `TOOL_SCHEMAS = [...]` list and append a new schema entry just before the closing `]`:

```python
    {
        "name": "recall_decisions",
        "description": "Return a chronological timeline of decision-kind facts whose text mentions the given topic. Use this when the user asks 'what did we decide about X' or anything implying a structured decision history. Returns most recent first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic substring; case-insensitive match against the fact text."},
                "entity": {"type": "string", "description": "Optional entity slug (amzg/seo) to restrict the search. Omit for cross-entity."},
            },
            "required": ["topic"],
        },
    },
```

Find the existing `execute_tool` dispatcher (the chain of `if name == "..."` branches). Add a new branch just before `raise ValueError(...)`:

```python
    if name == "recall_decisions":
        return _recall_decisions(ctx, arguments)
```

At the top of `goldman/bot/tools.py`, find the existing import of `hybrid_search` and add a sibling line:

```python
from goldman.decisions import decision_timeline
```

At the bottom of `goldman/bot/tools.py`, add the helper function:

```python
def _recall_decisions(ctx, args) -> str:
    topic = args["topic"].strip()
    entity_slug = args.get("entity") or ctx.entity_slug
    try:
        results = decision_timeline(
            conn=ctx.conn, topic=topic, entity_slug=entity_slug,
        )
    except ValueError as e:
        return f"Cannot run recall_decisions: {e}"

    if not results:
        scope = f" for {entity_slug}" if entity_slug else ""
        return f"No prior decisions{scope} matching {topic!r}."

    header = f"Decision timeline for {topic!r}:"
    lines = [header]
    for r in results:
        date_part = (r["created_at"] or "")[:10] or "(unknown date)"
        ent_part = f" ({r['entity_slug']})" if r["entity_slug"] else ""
        lines.append(f"  {date_part}: {r['fact']}{ent_part}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run — should pass**

```bash
python3 -m pytest tests/test_goldman_bot_tools.py -v 2>&1 | tail -10
```

Expected: 6 tests pass (3 existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add goldman/bot/tools.py tests/test_goldman_bot_tools.py && \
git commit -m "Phase 6.5: add recall_decisions bot tool

Registers in TOOL_SCHEMAS. _recall_decisions calls decision_timeline
and formats as 'Decision timeline for X:' + dated bullets. Empty case
returns 'No prior decisions matching X.'

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Persona update (TDD)

**Files:**
- Modify: `goldman/bot/handlers.py`
- Modify: `tests/test_goldman_bot_handlers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_goldman_bot_handlers.py`:

```python
def test_goldman_persona_mentions_recall_decisions_tool():
    from goldman.bot.handlers import GOLDMAN_PERSONA
    assert "recall_decisions" in GOLDMAN_PERSONA
    assert "decide" in GOLDMAN_PERSONA.lower()
```

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_bot_handlers.py::test_goldman_persona_mentions_recall_decisions_tool -v 2>&1 | tail -5
```

Expected: AssertionError.

- [ ] **Step 3: Update `GOLDMAN_PERSONA`**

Open `goldman/bot/handlers.py`. Find the existing `GOLDMAN_PERSONA = """\` block and the line that says `You have tools to recall memory, look up the company structure,\nlist invoices, and remember facts. Use them.`. Insert this new paragraph immediately after that line (before the existing `CITATION RULES` block):

```
For "what did we decide" questions, or anything implying a structured
timeline of prior decisions, prefer the recall_decisions tool over
recall — it returns chronological decision-kind facts, not a similarity
search.

```

(Keep the blank line between this new paragraph and the next.)

- [ ] **Step 4: Run — should pass**

```bash
python3 -m pytest tests/test_goldman_bot_handlers.py -v 2>&1 | tail -7
```

Expected: 4 tests pass (3 existing + 1 new).

- [ ] **Step 5: Commit**

```bash
git add goldman/bot/handlers.py tests/test_goldman_bot_handlers.py && \
git commit -m "Phase 6.5: teach persona about recall_decisions

One sentence: prefer recall_decisions for 'what did we decide' questions
instead of generic recall.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: API endpoint `/v1/decisions` (TDD)

**Files:**
- Modify: `goldman/api/endpoints.py`
- Modify: `tests/test_goldman_api_endpoints.py`
- Modify: `main.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_goldman_api_endpoints.py`:

```python
def test_handle_decisions_returns_decision_list():
    fake_results = [
        {"id": uuid4(),
         "fact": "Hire UK accountant for VAT filings",
         "entity_slug": "amzg",
         "created_at": "2026-06-08T00:00:00+00:00",
         "supersedes_id": None},
    ]
    with patch("goldman.api.endpoints.app_conn") as mock_conn, \
         patch("goldman.api.endpoints.decision_timeline",
                return_value=fake_results):
        mock_conn.return_value.__enter__.return_value = MagicMock()

        code, body = handle_decisions(
            query={}, body={"topic": "VAT", "entity": "amzg"},
        )

        assert code == 200
        assert "decisions" in body
        assert len(body["decisions"]) == 1
        assert body["decisions"][0]["fact"] == "Hire UK accountant for VAT filings"


def test_handle_decisions_400_when_topic_missing():
    code, body = handle_decisions(query={}, body={})
    assert code == 400
    assert "topic" in body["error"].lower()


def test_handle_decisions_400_when_topic_blank():
    code, body = handle_decisions(query={}, body={"topic": "   "})
    assert code == 400
```

Also at the top of `tests/test_goldman_api_endpoints.py`, find the existing import block and add:

```python
from goldman.api.endpoints import handle_decisions
```

(Add it to the existing line `from goldman.api.endpoints import (...)` — extend the list.)

- [ ] **Step 2: Run — confirm failure**

```bash
python3 -m pytest tests/test_goldman_api_endpoints.py::test_handle_decisions_returns_decision_list -v 2>&1 | tail -5
```

Expected: `ImportError: cannot import name 'handle_decisions' from 'goldman.api.endpoints'`.

- [ ] **Step 3: Implement `handle_decisions`**

Open `goldman/api/endpoints.py`. At the top, add:

```python
from goldman.decisions import decision_timeline
```

At the bottom of the file (after `handle_status`), add:

```python
def handle_decisions(*, query: dict, body: dict) -> tuple:
    body = body or {}
    topic = (body.get("topic") or "").strip()
    if not topic:
        return 400, {"error": "Missing or empty 'topic' in body."}

    entity = body.get("entity")
    limit = int(body.get("limit", 20))

    with app_conn() as conn:
        results = decision_timeline(
            conn=conn, topic=topic, entity_slug=entity, limit=limit,
        )

    return 200, {
        "decisions": [
            {"id": str(r["id"]),
             "fact": r["fact"],
             "entity_slug": r["entity_slug"],
             "created_at": r["created_at"],
             "supersedes_id": str(r["supersedes_id"]) if r["supersedes_id"] else None}
            for r in results
        ],
    }
```

- [ ] **Step 4: Wire route in `main.py`**

Open `main.py`. Find the `_handle_api` method inside `_HealthHandler`. Find the existing dispatcher block (a chain of `if path == "/v1/who": ...` branches). Find the `elif path == "/v1/status":` line. Immediately before it, add a new branch:

```python
            elif path == "/v1/decisions":
                code, payload = handle_decisions(query=query, body=body)
```

Also update the import block in the same method:

```python
        from goldman.api.endpoints import (
            handle_who, handle_recall, handle_remember,
            handle_pending_bills, handle_status, handle_decisions,
        )
```

- [ ] **Step 5: Run — all tests pass**

```bash
python3 -m pytest tests/test_goldman_api_endpoints.py -v 2>&1 | tail -12
```

Expected: 9 tests pass (6 existing + 3 new).

- [ ] **Step 6: Verify main.py compiles**

```bash
python3 -c "import main; print('OK')"
```

Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add goldman/api/endpoints.py tests/test_goldman_api_endpoints.py main.py && \
git commit -m "Phase 6.5: add /v1/decisions endpoint

POST /v1/decisions with {topic, entity?, limit?} body. Returns
{decisions: [...]} or 400 when topic is missing or blank. Wired into
main.py _handle_api dispatcher.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Plugin `/goldman:decisions` slash command

**Files:**
- Create: `goldman.plugin/commands/decisions.md`

- [ ] **Step 1: Create the command file**

Create `goldman.plugin/commands/decisions.md`:

```markdown
---
description: Chronological timeline of decisions matching a topic.
argument-hint: <topic>
allowed-tools: Bash(curl:*), Bash(jq:*)
---

```bash
URL="${GOLDMAN_API_URL:-https://goldman.onrender.com}"
KEY="${GOLDMAN_API_KEY:-}"
TOPIC="$ARGUMENTS"
if [ -z "$TOPIC" ]; then
  echo "Usage: /goldman:decisions <topic>"
  exit 1
fi
curl -s -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "{\"topic\":\"$TOPIC\"}" "$URL/v1/decisions" | \
  jq -r '
    if (.decisions | length) == 0 then
      "No prior decisions matching \"" + ($ENV.TOPIC // "") + "\"."
    else
      "Decision timeline for \"" + ($ENV.TOPIC // "") + "\":\n" +
      (.decisions | map(
        "  " + (.created_at[0:10]) + ": " + .fact +
        (if .entity_slug then " (\(.entity_slug))" else "" end)
      ) | join("\n"))
    end
  ' TOPIC="$TOPIC"
```
```

- [ ] **Step 2: Commit**

```bash
git add goldman.plugin/commands/decisions.md && \
git commit -m "Phase 6.5: add /goldman:decisions slash command

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Full regression + memory update

**Files:** (no code changes; checkpoint)

- [ ] **Step 1: Full sweep**

```bash
cd ~/Desktop/Obsidian/Projects/zoho-invoice-agent && \
python3 -m pytest 2>&1 | tail -3
```

Expected: every test passes. Prior 179 + Phase 6.5's 7 new = ~186 total.

- [ ] **Step 2: Verify CLI imports unchanged (sanity)**

```bash
python3 -c "import cli; print('cli OK')"
```

Expected: `cli OK`.

- [ ] **Step 3: Verify API endpoint registered (sanity)**

```bash
python3 -c "
from goldman.api.endpoints import handle_decisions
print('handle_decisions OK')
"
```

Expected: `handle_decisions OK`.

- [ ] **Step 4: Update memory**

Append to `~/.claude/projects/-Users-hamburg/memory/project_goldman.md`:

```markdown
- **Phase 6.5 (decision recall) code = COMPLETE 2026-06-09.** New module `goldman/decisions.py` with `decision_timeline(conn, topic, entity_slug=None, limit=20)` — queries `goldman.facts_live JOIN goldman.entities` WHERE kind='decision' AND fact ILIKE topic, ORDER BY created_at DESC. Returns list of `{id, fact, entity_slug, created_at, supersedes_id}`. New bot tool `recall_decisions` registered in TOOL_SCHEMAS; persona updated to prefer it for 'what did we decide' questions. New API endpoint POST `/v1/decisions` (body: `{topic, entity?, limit?}` → `{decisions: [...]}`) wired into main.py dispatcher. New plugin slash command `/goldman:decisions <topic>`. 7 new tests, ~186 total pass. No schema migration. Empty until Liran has accumulated decision-kind facts via onboarding or `remember --kind decision`.
```

---

## Spec coverage cross-check

| Spec section | Covered by task(s) |
|---|---|
| §2 — `decision_timeline` function | Task 1 |
| §2 — bot tool `recall_decisions` | Task 2 |
| §2 — persona one-sentence addition | Task 3 |
| §2 — `/v1/decisions` API endpoint | Task 4 |
| §2 — `/goldman:decisions` plugin slash command | Task 5 |
| §4 — substring + entity filter + order | Task 1 SQL |
| §5 — failure modes (empty topic, no matches, entity not found, superseded facts) | Tasks 1, 2 |
| §7 — implementation tasks | Tasks 1-6 |

All spec requirements covered.

---

## What's intentionally NOT in this plan

- CLI command `cli.py decisions` — bot + plugin cover the surface per spec §6.
- Semantic / embedding-based matching — v2 if Liran reports paraphrase misses.
- Decision provenance display (linking back to source conversation turns or documents).
- Cross-supersedes chain display.
- Topic auto-grouping.
