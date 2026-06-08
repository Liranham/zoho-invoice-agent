# Goldman Phase 5 — Claude Code Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Goldman becomes a Claude Code plugin (`goldman.plugin`). Slash commands `/goldman:who`, `/goldman:recall`, `/goldman:remember`, `/goldman:invoice`, `/goldman:status`, `/goldman:explain` reach Goldman from any Claude session — local terminal or Cowork. Each command calls Goldman's HTTP API on Render (same brain that powers the Telegram bot). Liran can install the plugin once and Goldman is available everywhere.

**Architecture:** Two layers. (1) Goldman service grows a small REST API surface (`/v1/who`, `/v1/recall`, etc.) on the existing health-server port; auth via a single Bearer token (`GOLDMAN_API_KEY`). (2) A `goldman.plugin/` directory at repo root that follows Claude Code's plugin schema — `plugin.json` manifest + `commands/*.md` with frontmatter + bash body that curls the API and prints JSON-formatted output. No new tables; no schema changes. Phase 5 is glue.

**Tech Stack:** Pure stdlib HTTP (existing `_HealthHandler`), `requests` (already a dep) for plugin bash scripts (via `curl` actually — plugins are language-agnostic, bash is fine). Claude Code plugin format (manifest v1).

---

## File Map

**Create:**
- `goldman/api/__init__.py`
- `goldman/api/auth.py` — Bearer-token auth check.
- `goldman/api/endpoints.py` — request routers per endpoint.
- `goldman.plugin/.claude-plugin/plugin.json` — plugin manifest.
- `goldman.plugin/commands/who.md` — `/goldman:who`.
- `goldman.plugin/commands/recall.md` — `/goldman:recall`.
- `goldman.plugin/commands/remember.md` — `/goldman:remember`.
- `goldman.plugin/commands/invoice.md` — `/goldman:invoice`.
- `goldman.plugin/commands/status.md` — `/goldman:status`.
- `goldman.plugin/commands/explain.md` — `/goldman:explain`.
- `goldman.plugin/README.md` — install instructions.
- `tests/test_goldman_api_auth.py`
- `tests/test_goldman_api_endpoints.py`

**Modify:**
- `main.py` — wire the new endpoints into `_HealthHandler` (auth-gated).
- `.env.example` — document `GOLDMAN_API_KEY` and `GOLDMAN_API_URL` (the latter is what the plugin reads).

---

## Task 1: API auth helper (TDD)

**Files:**
- Create: `goldman/api/__init__.py`, `goldman/api/auth.py`, `tests/test_goldman_api_auth.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the API auth check."""

from __future__ import annotations

from goldman.api.auth import is_authorized


def test_is_authorized_accepts_matching_bearer(monkeypatch):
    monkeypatch.setenv("GOLDMAN_API_KEY", "secret_xyz")
    assert is_authorized({"Authorization": "Bearer secret_xyz"}) is True


def test_is_authorized_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("GOLDMAN_API_KEY", "secret_xyz")
    assert is_authorized({"Authorization": "Bearer nope"}) is False


def test_is_authorized_rejects_missing_header(monkeypatch):
    monkeypatch.setenv("GOLDMAN_API_KEY", "secret_xyz")
    assert is_authorized({}) is False


def test_is_authorized_denies_when_key_not_set(monkeypatch):
    monkeypatch.delenv("GOLDMAN_API_KEY", raising=False)
    assert is_authorized({"Authorization": "Bearer anything"}) is False
```

- [ ] **Step 2: Implement**

Create `goldman/api/__init__.py`:
```python
"""Goldman HTTP API (Phase 5 — Claude Code plugin server side)."""
```

Create `goldman/api/auth.py`:
```python
"""Bearer-token auth check.

Single shared secret in GOLDMAN_API_KEY. Single-user; no rotation in v1.
"""

from __future__ import annotations

import hmac
import os


def is_authorized(headers: dict) -> bool:
    expected = os.getenv("GOLDMAN_API_KEY", "")
    if not expected:
        return False
    raw = headers.get("Authorization") or headers.get("authorization") or ""
    if not raw.startswith("Bearer "):
        return False
    token = raw[len("Bearer "):].strip()
    return hmac.compare_digest(token, expected)
```

- [ ] **Step 3: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_api_auth.py -v 2>&1 | tail -7 && \
git add goldman/api/__init__.py goldman/api/auth.py tests/test_goldman_api_auth.py && \
git commit -m "Add API auth helper (Bearer-token check via GOLDMAN_API_KEY)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 4 tests pass.

---

## Task 2: API endpoint handlers (TDD)

**Files:** Create: `goldman/api/endpoints.py`, `tests/test_goldman_api_endpoints.py`

Endpoints return `(status_code, body_dict)` tuples. The main.py handler wires them into HTTP responses.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the API endpoint handlers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from goldman.api.endpoints import (
    handle_who, handle_recall, handle_remember,
    handle_pending_bills, handle_status,
)


def test_handle_who_returns_summary_list():
    with patch("goldman.api.endpoints.app_conn") as mock_conn, \
         patch("goldman.api.endpoints.build_who_view") as mock_build:
        mock_conn.return_value.__enter__.return_value = MagicMock()
        mock_build.return_value = [
            MagicMock(slug="amzg", legal_name="AMZ Expert Global Limited",
                       jurisdiction="HK", tax_registrations=[],
                       bank_accounts=[], top_clients=[], top_vendors=[]),
        ]

        code, body = handle_who(query={}, body={})

        assert code == 200
        assert "entities" in body
        assert body["entities"][0]["slug"] == "amzg"


def test_handle_recall_returns_results(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    with patch("goldman.api.endpoints.app_conn") as mock_conn, \
         patch("goldman.api.endpoints.EmbeddingClient") as mock_emb, \
         patch("goldman.api.endpoints.hybrid_search") as mock_search:
        mock_conn.return_value.__enter__.return_value = MagicMock()
        mock_emb.return_value.embed_batch.return_value = [[0.1] * 1536]
        from uuid import uuid4
        mock_search.return_value = [
            MagicMock(source_type="fact", source_id=uuid4(),
                       excerpt="UK VAT registered", score=0.42,
                       entity_id=None, metadata={}),
        ]

        code, body = handle_recall(query={}, body={"question": "VAT?"})

        assert code == 200
        assert "results" in body
        assert body["results"][0]["source_type"] == "fact"


def test_handle_recall_400_without_question():
    code, body = handle_recall(query={}, body={})
    assert code == 400
    assert "question" in body["error"].lower()


def test_handle_remember_returns_fact_id():
    with patch("goldman.api.endpoints.app_conn") as mock_conn, \
         patch("goldman.api.endpoints.FactRepository") as mock_facts, \
         patch("goldman.api.endpoints.EntityRepository") as mock_ents:
        mock_conn.return_value.__enter__.return_value = MagicMock()
        from uuid import uuid4
        fid = uuid4()
        mock_facts.return_value.upsert.return_value = fid
        mock_ents.return_value.get_by_slug.return_value = MagicMock(id=uuid4())

        code, body = handle_remember(
            query={},
            body={"entity": "amzg", "kind": "decision", "text": "use Wise"},
        )

        assert code == 201
        assert body["fact_id"] == str(fid)


def test_handle_pending_bills_lists_open():
    with patch("goldman.api.endpoints.app_conn") as mock_conn, \
         patch("goldman.api.endpoints.BillRepository") as mock_bills:
        mock_conn.return_value.__enter__.return_value = MagicMock()
        mock_bills.return_value.list_pending_partial_writes.return_value = []

        code, body = handle_pending_bills(query={}, body={})

        assert code == 200
        assert "bills" in body
        assert body["bills"] == []


def test_handle_status_returns_service_health():
    with patch("goldman.api.endpoints.app_conn") as mock_conn:
        cur = MagicMock()
        cur.fetchone.return_value = (5,)
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur

        code, body = handle_status(query={}, body={})

        assert code == 200
        assert body["service"] == "goldman"
        assert "entities" in body
```

- [ ] **Step 2: Implement**

Create `goldman/api/endpoints.py`:

```python
"""HTTP endpoint handlers for the Goldman API (Phase 5 plugin server)."""

from __future__ import annotations

import os
from typing import Optional

from goldman.who import build_who_view
from goldman_db.connection import app_conn
from goldman_db.entities import EntityRepository


def _serialise_summary(s) -> dict:
    return {
        "slug": s.slug,
        "legal_name": s.legal_name,
        "jurisdiction": s.jurisdiction,
        "parent_entity_id": str(s.parent_entity_id) if getattr(s, "parent_entity_id", None) else None,
        "base_currency": s.base_currency,
        "fiscal_year_end": s.fiscal_year_end,
        "registered_address": s.registered_address,
        "company_number": s.company_number,
        "tax_registrations": [
            {"tax_type": tr.tax_type, "jurisdiction": tr.jurisdiction,
             "registration_number": tr.registration_number,
             "filing_cadence": tr.filing_cadence}
            for tr in s.tax_registrations
        ],
        "bank_accounts": [
            {"provider": b.provider, "account_label": b.account_label,
             "currency": b.currency}
            for b in s.bank_accounts
        ],
        "top_clients": [
            {"name": c.contact_name, "tier": c.tier}
            for c in s.top_clients
        ],
        "top_vendors": [
            {"name": v.vendor_name, "category": v.category}
            for v in s.top_vendors
        ],
    }


def handle_who(*, query: dict, body: dict) -> tuple:
    from goldman_db.bank_accounts import BankAccountRepository
    from goldman_db.clients import ClientRepository
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
    return 200, {"entities": [_serialise_summary(s) for s in summaries]}


def handle_recall(*, query: dict, body: dict) -> tuple:
    from goldman.embeddings import EmbeddingClient
    from goldman_db.hybrid_search import hybrid_search

    question = (body or {}).get("question") or query.get("q", [""])[0]
    if not question:
        return 400, {"error": "Missing 'question' in body."}

    entity_slug = (body or {}).get("entity") or query.get("entity", [None])[0]
    top_n = int((body or {}).get("top", 10))

    embedder = EmbeddingClient()
    vec = embedder.embed_batch([question])[0]

    with app_conn() as conn:
        entity_id = None
        if entity_slug:
            ent = EntityRepository(conn).get_by_slug(entity_slug.lower())
            if ent:
                entity_id = ent.id
        results = hybrid_search(
            conn, query_embedding=vec, query_text=question,
            entity_id=entity_id, top_n=top_n,
        )

    return 200, {
        "results": [
            {"source_type": r.source_type, "source_id": str(r.source_id),
             "excerpt": r.excerpt[:500], "score": r.score,
             "metadata": r.metadata}
            for r in results
        ],
    }


def handle_remember(*, query: dict, body: dict) -> tuple:
    from goldman_db.facts import FactRepository

    body = body or {}
    text = body.get("text")
    kind = body.get("kind", "note")
    entity = body.get("entity", "amzg")
    if not text:
        return 400, {"error": "Missing 'text' in body."}
    if kind not in {"target", "preference", "constraint",
                     "commitment", "event", "decision", "note"}:
        return 400, {"error": f"Bad kind: {kind}"}

    with app_conn() as conn:
        entity_id = None
        if entity and entity != "global":
            ent = EntityRepository(conn).get_by_slug(entity.lower())
            entity_id = ent.id if ent else None
        new_id = FactRepository(conn).upsert(
            entity_id=entity_id, kind=kind, fact=text,
            source="user_explicit",
        )

    return 201, {"fact_id": str(new_id), "kind": kind, "entity": entity}


def handle_pending_bills(*, query: dict, body: dict) -> tuple:
    from goldman_db.bills import BillRepository

    with app_conn() as conn:
        bills = BillRepository(conn).list_pending_partial_writes(limit=50)

    return 200, {
        "bills": [
            {
                "id": str(b.id),
                "vendor": b.vendor_name_at_intake,
                "amount": float(b.amount), "currency": b.currency,
                "in_storage": b.in_storage,
                "in_drive": b.in_drive,
                "in_zoho": b.in_zoho,
                "status": b.status,
                "last_error": b.last_error,
            }
            for b in bills
        ],
    }


def handle_status(*, query: dict, body: dict) -> tuple:
    with app_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM goldman.entities")
            entities = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM goldman.bills WHERE status = 'pending' OR status = 'partial'")
            pending_bills = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM goldman.pending_confirmations WHERE answered_at IS NULL")
            pending_confs = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM goldman.facts WHERE embedding IS NULL")
            facts_to_embed = cur.fetchone()[0]

    return 200, {
        "service": "goldman",
        "entities": entities,
        "pending_bills": pending_bills,
        "pending_confirmations": pending_confs,
        "facts_awaiting_embedding": facts_to_embed,
    }
```

- [ ] **Step 3: Run + Commit**

```bash
python3 -m pytest tests/test_goldman_api_endpoints.py -v 2>&1 | tail -10 && \
git add goldman/api/endpoints.py tests/test_goldman_api_endpoints.py && \
git commit -m "Add API endpoint handlers (who/recall/remember/pending_bills/status)

Returns (status_code, body_dict) tuples; main.py wires HTTP shapes.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: 6 tests pass.

---

## Task 3: Wire endpoints into main.py

**Files:** Modify: `main.py`

- [ ] **Step 1: Add routes inside `_HealthHandler`**

In `main.py`, modify `_HealthHandler.do_GET` and add `_handle_api_get` / `_handle_api_post`:

In `do_GET`, add a new branch BEFORE the `404 not found` branch:

```python
        elif self.path.startswith("/v1/"):
            self._handle_api(method="GET")
            return
```

In `do_POST`, add a new branch BEFORE the `404 not found` branch:

```python
        elif self.path.startswith("/v1/"):
            self._handle_api(method="POST")
            return
```

Then add this method inside `_HealthHandler`:

```python
    def _handle_api(self, method: str):
        from urllib.parse import urlparse, parse_qs
        from goldman.api.auth import is_authorized
        from goldman.api.endpoints import (
            handle_who, handle_recall, handle_remember,
            handle_pending_bills, handle_status,
        )

        if not is_authorized(dict(self.headers)):
            self._json_response(401, {"error": "unauthorized"})
            return

        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        body = {}
        if method == "POST":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length:
                    raw = self.rfile.read(content_length)
                    body = json.loads(raw.decode("utf-8"))
            except Exception as e:
                self._json_response(400, {"error": f"bad json: {e}"})
                return

        try:
            if path == "/v1/who":
                code, payload = handle_who(query=query, body=body)
            elif path == "/v1/recall":
                code, payload = handle_recall(query=query, body=body)
            elif path == "/v1/remember":
                code, payload = handle_remember(query=query, body=body)
            elif path == "/v1/bills/pending":
                code, payload = handle_pending_bills(query=query, body=body)
            elif path == "/v1/status":
                code, payload = handle_status(query=query, body=body)
            else:
                code, payload = 404, {"error": f"unknown api path: {path}"}
        except Exception as e:
            logger.exception("API error: %s", e)
            code, payload = 500, {"error": str(e)}

        self._json_response(code, payload)
```

- [ ] **Step 2: Verify imports compile**

```bash
python3 -c "import main; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add main.py && git commit -m "main.py: wire /v1/* API routes (auth-gated, JSON in/out)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Plugin manifest + structure

**Files:**
- Create: `goldman.plugin/.claude-plugin/plugin.json`
- Create: `goldman.plugin/README.md`

- [ ] **Step 1: Write the manifest**

Create `goldman.plugin/.claude-plugin/plugin.json`:

```json
{
  "name": "goldman",
  "description": "Goldman — CFO of AMZ Expert Global Limited. Slash commands talk to the Render-hosted Goldman service over HTTPS.",
  "version": "0.1.0",
  "author": { "name": "Liran Hamburg" },
  "license": "UNLICENSED"
}
```

- [ ] **Step 2: Write the README**

Create `goldman.plugin/README.md`:

```markdown
# Goldman — Claude Code plugin

Slash commands that call the Goldman HTTP API on Render.

## Install

In any Claude Code session:

```bash
/plugin install /absolute/path/to/goldman.plugin
```

Then set these env vars in `~/.bashrc` (or session env):

```bash
export GOLDMAN_API_URL="https://goldman.onrender.com"   # or your service URL
export GOLDMAN_API_KEY="<the bearer token>"
```

## Commands

- `/goldman:who` — print the company tree
- `/goldman:status` — service health + pending counts
- `/goldman:recall <question>` — hybrid search across memory
- `/goldman:remember <kind> <text>` — record a fact
- `/goldman:invoice` — list recent invoices (TBD: alias the Phase 0 endpoint)
- `/goldman:explain <topic>` — Goldman writes a short explanation grounded in his memory
```

- [ ] **Step 3: Commit**

```bash
git add goldman.plugin/.claude-plugin/plugin.json goldman.plugin/README.md && \
git commit -m "Add Goldman plugin scaffold (manifest + README)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: /goldman:who command

**Files:** Create: `goldman.plugin/commands/who.md`

- [ ] **Step 1: Write the command file**

```markdown
---
description: Print Goldman's company tree (entities, registrations, banks, top clients/vendors).
allowed-tools: Bash(curl:*), Bash(jq:*)
---

Call Goldman's /v1/who endpoint and render the result.

```bash
URL="${GOLDMAN_API_URL:-https://goldman.onrender.com}"
KEY="${GOLDMAN_API_KEY:-}"
if [ -z "$KEY" ]; then
  echo "GOLDMAN_API_KEY not set"
  exit 1
fi
curl -s -H "Authorization: Bearer $KEY" "$URL/v1/who" | \
  jq -r '
    .entities[] |
    "\n\(.legal_name) (\(.slug))" + 
    "\n  Jurisdiction:    \(.jurisdiction)" +
    "\n  Tax registrations: \(.tax_registrations | length)" +
    "\n  Bank accounts:     \(.bank_accounts | length)" +
    "\n  Top clients:       \(.top_clients | length)" +
    "\n  Top vendors:       \(.top_vendors | length)"
  '
```
```

- [ ] **Step 2: Commit**

```bash
git add goldman.plugin/commands/who.md && \
git commit -m "Add /goldman:who slash command

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: /goldman:recall command

**Files:** Create: `goldman.plugin/commands/recall.md`

```markdown
---
description: Hybrid search over Goldman's memory (facts, conversations, documents).
argument-hint: <question>
allowed-tools: Bash(curl:*), Bash(jq:*)
---

```bash
URL="${GOLDMAN_API_URL:-https://goldman.onrender.com}"
KEY="${GOLDMAN_API_KEY:-}"
QUESTION="$ARGUMENTS"
if [ -z "$QUESTION" ]; then
  echo "Usage: /goldman:recall <question>"
  exit 1
fi
curl -s -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "{\"question\":\"$QUESTION\",\"top\":8}" "$URL/v1/recall" | \
  jq -r '
    .results[] |
    "\n[\(.source_type)] score=\(.score)\n  \(.excerpt[:200])"
  '
```
```

- [ ] **Commit**

```bash
git add goldman.plugin/commands/recall.md && \
git commit -m "Add /goldman:recall slash command

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: /goldman:remember command

**Files:** Create: `goldman.plugin/commands/remember.md`

```markdown
---
description: Record a structured fact for an entity.
argument-hint: <kind> <text>
allowed-tools: Bash(curl:*), Bash(jq:*)
---

```bash
URL="${GOLDMAN_API_URL:-https://goldman.onrender.com}"
KEY="${GOLDMAN_API_KEY:-}"
KIND=$(echo "$ARGUMENTS" | awk '{print $1}')
TEXT=$(echo "$ARGUMENTS" | cut -d' ' -f2-)
if [ -z "$KIND" ] || [ -z "$TEXT" ]; then
  echo "Usage: /goldman:remember <kind> <text>"
  echo "Kinds: target|preference|constraint|commitment|event|decision|note"
  exit 1
fi
curl -s -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "{\"entity\":\"amzg\",\"kind\":\"$KIND\",\"text\":\"$TEXT\"}" "$URL/v1/remember" | \
  jq -r '"Stored fact \(.fact_id) (kind=\(.kind))"'
```
```

- [ ] **Commit**

```bash
git add goldman.plugin/commands/remember.md && \
git commit -m "Add /goldman:remember slash command

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: /goldman:status command

**Files:** Create: `goldman.plugin/commands/status.md`

```markdown
---
description: Service health + pending bills + pending confirmations.
allowed-tools: Bash(curl:*), Bash(jq:*)
---

```bash
URL="${GOLDMAN_API_URL:-https://goldman.onrender.com}"
KEY="${GOLDMAN_API_KEY:-}"
curl -s -H "Authorization: Bearer $KEY" "$URL/v1/status" | jq .
```
```

- [ ] **Commit**

```bash
git add goldman.plugin/commands/status.md && \
git commit -m "Add /goldman:status slash command

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: /goldman:invoice command

**Files:** Create: `goldman.plugin/commands/invoice.md`

`/goldman:invoice` lists recent invoices via the existing `/invoices?entity=...` endpoint.

```markdown
---
description: List recent client invoices for an entity (default amzg).
argument-hint: [entity-slug]
allowed-tools: Bash(curl:*), Bash(jq:*)
---

```bash
URL="${GOLDMAN_API_URL:-https://goldman.onrender.com}"
KEY="${GOLDMAN_API_KEY:-}"
ENTITY="${ARGUMENTS:-amzg}"
curl -s -H "Authorization: Bearer $KEY" "$URL/invoices?entity=$ENTITY" | \
  jq -r '
    .invoices[] |
    "\(.invoice_number) | \(.status) | \(.date) | \(.total) | \(.customer)"
  '
```
```

Note: the existing `/invoices` endpoint pre-dates Phase 5's auth; it's reachable without the API key today. Phase 5.1 (future) will move it under `/v1/`.

- [ ] **Commit**

```bash
git add goldman.plugin/commands/invoice.md && \
git commit -m "Add /goldman:invoice slash command

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: /goldman:explain command

`/goldman:explain <topic>` — Goldman writes a short explanation grounded in his memory. This is implemented as a Claude Code skill that calls `/v1/recall` then asks Claude (the parent session) to synthesise.

**Files:** Create: `goldman.plugin/commands/explain.md`

```markdown
---
description: Goldman explains a topic in plain English, grounded in his memory.
argument-hint: <topic>
allowed-tools: Bash(curl:*), Bash(jq:*)
---

Step 1 — pull relevant memory:

```bash
URL="${GOLDMAN_API_URL:-https://goldman.onrender.com}"
KEY="${GOLDMAN_API_KEY:-}"
TOPIC="$ARGUMENTS"
curl -s -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "{\"question\":\"$TOPIC\",\"top\":10}" "$URL/v1/recall" | \
  jq -r '.results | map("- [\(.source_type)] \(.excerpt[:250])") | join("\n")'
```

Step 2 — synthesise:

Read the memory chunks above. Write 2-3 short paragraphs in plain English
that explain "$ARGUMENTS" using ONLY what's in those chunks. Cite the
chunks by source_type. If the memory doesn't cover the topic, say so
clearly — do NOT invent.
```

- [ ] **Commit**

```bash
git add goldman.plugin/commands/explain.md && \
git commit -m "Add /goldman:explain slash command

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 11: Document env vars + final regression

**Files:** Modify: `.env.example`

- [ ] **Step 1: Append**

```bash

# ============================================================================
# Goldman Phase 5 — Claude Code plugin / HTTP API
# ============================================================================
# Bearer token the plugin sends. Same value MUST be in the plugin's env.
GOLDMAN_API_KEY=
```

- [ ] **Step 2: Full sweep**

```bash
cd ~/Desktop/Obsidian/Projects/zoho-invoice-agent && python3 -m pytest 2>&1 | tail -3
```

Expected: 156 + 10 = 166 tests pass.

- [ ] **Step 3: CLI surface check**

```bash
python3 cli.py --help 2>&1 | tail -15
```

Expected: all phase 0-4 commands present.

- [ ] **Step 4: Plugin file listing**

```bash
find goldman.plugin -type f | sort
```

Expected: manifest + 6 command files + README.

- [ ] **Step 5: Commit**

```bash
git add .env.example && \
git commit -m "Document Phase 5 GOLDMAN_API_KEY env var

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

- [ ] **Step 6: Update memory**

Append to `~/.claude/projects/-Users-hamburg/memory/project_goldman.md`:

```markdown
- **Phase 5 code = COMPLETE.** Claude Code plugin: goldman.plugin/ with 6 slash commands (/goldman:who, /goldman:recall, /goldman:remember, /goldman:status, /goldman:invoice, /goldman:explain). Plugin commands curl Goldman's new /v1/* HTTP API. API auth: Bearer token in GOLDMAN_API_KEY. Endpoints: /v1/who, /v1/recall, /v1/remember, /v1/bills/pending, /v1/status. Plugin install: `/plugin install /absolute/path/to/goldman.plugin` in any Claude Code session, then set GOLDMAN_API_URL + GOLDMAN_API_KEY env. 10 new tests, 166 total. **Phase 5 completes the bookkeeper-grade Goldman shipping milestone — stop-and-decide point per spec §10 before Phase 6 advisor depth.**
```

---

## Spec coverage cross-check

| Spec section | Covered by task(s) |
|---|---|
| §8.2 — Plugin installable in Claude Code | Tasks 4 (manifest), 5-10 (commands) |
| §8.2 — Skills /goldman:who/recall/remember/status/invoice/explain | Tasks 5-10 |
| §8.2 — Calls Goldman HTTP API on Render | Tasks 1-3 (auth + endpoints + main.py wiring), Tasks 5-10 (commands curl the API) |
| §8.2 — Same brain as Telegram | API endpoints reuse Phase 0-3 repos and the same app_conn |
| §8.2 — Auth + tenant routing | Task 1 (single shared GOLDMAN_API_KEY; single-user system) |

All Phase 5 spec requirements have at least one implementing task.

---

## What's intentionally NOT in this plan

- Plugin marketplace publication — local install only for v1.
- File upload via plugin (e.g. `/goldman:bill <path>` parsing a local PDF) — the slash command can't easily ship binary; defer to Phase 5.1.
- Granular per-command API keys / scopes — single shared key v1.
- WebSocket / streaming — REST only.
- Plugin auto-update — install via path; pull the latest by `git pull` in the repo.
