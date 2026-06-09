"""MCP (Model Context Protocol) server endpoint for Goldman.

Lets claude.ai (and other MCP-aware clients like Claude Desktop and
Claude Code MCP support) call Goldman's tools directly through the
official protocol. Wraps the same tools the Telegram bot uses.

Spec: https://modelcontextprotocol.io/specification/2025-06-18

Transport: streamable HTTP (single POST endpoint, JSON or SSE response).
Auth: Bearer token in `Authorization: Bearer <GOLDMAN_API_KEY>` header,
identical to the existing /v1/* REST endpoints.

Methods implemented:
- initialize         — protocol handshake
- tools/list         — advertises Goldman's tools
- tools/call         — runs a tool
- notifications/initialized — no-op accept
- ping               — health
"""

from __future__ import annotations

import json
import os
import traceback


PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "goldman", "version": "1.0.0"}


# Tools exposed to claude.ai. Mirrors goldman.bot.tools.TOOL_SCHEMAS but
# adds an `entity` / `channel_id` argument where useful so external
# callers can scope queries.
TOOLS = [
    {
        "name": "ask_goldman",
        "description": (
            "Have a free-form conversation with Goldman the CFO agent. "
            "Goldman manages AMZ-Expert Global Limited (HK parent) and "
            "Pacific Edge Outsourcing LLC (US subsidiary). He has memory "
            "of your decisions, vendors, banks, tax positions, and the "
            "contents of every document you've uploaded. Use this for ANY "
            "question about company structure, finances, taxes, vendors, "
            "clients, decisions, or to record a new fact."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "What you want to ask or tell Goldman, in plain English.",
                },
                "entity": {
                    "type": "string",
                    "enum": ["amzg", "seo", "all"],
                    "description": "Scope to one entity if relevant. Default 'all'.",
                    "default": "all",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "who",
        "description": (
            "Print Goldman's structured company brain: every entity with "
            "its tax registrations, bank accounts, top clients, top vendors, "
            "and intercompany flow. Use when the user asks 'what entities "
            "do I have' or 'show me my companies'."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "recall",
        "description": (
            "Keyword + recency search across Goldman's memory (facts + "
            "uploaded documents). Use when the user asks for a specific "
            "data point that might be in a document — EIN, BR number, "
            "bank account, address, etc."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "entity": {"type": "string",
                           "enum": ["amzg", "seo", "all"],
                           "default": "all"},
                "top_n": {"type": "integer", "default": 8},
            },
            "required": ["question"],
        },
    },
    {
        "name": "decisions",
        "description": (
            "Chronological timeline of past decisions matching a topic. "
            "Use when the user asks 'what did we decide about X'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "entity": {"type": "string",
                           "enum": ["amzg", "seo"]},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "remember",
        "description": (
            "Record a structured fact in Goldman's memory. Use when the "
            "user says 'remember that …' or 'note that …'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": ["target", "preference", "constraint",
                             "commitment", "event", "decision", "note"],
                    "default": "note",
                },
                "entity": {"type": "string",
                           "enum": ["amzg", "seo", "global"],
                           "default": "amzg"},
            },
            "required": ["text"],
        },
    },
]


def _is_authorized(headers: dict) -> bool:
    """Match the Bearer auth used by the existing /v1/* REST endpoints."""
    key = os.getenv("GOLDMAN_API_KEY", "")
    if not key:
        return False
    auth = ""
    for h in ("Authorization", "authorization"):
        if h in headers and headers[h]:
            auth = headers[h]
            break
    return auth == f"Bearer {key}"


def _error(req_id, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": code, "message": message},
    }


def _ok(req_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _run_tool(name: str, arguments: dict) -> str:
    """Dispatch a tool call to Goldman's existing handlers. Return text."""
    from goldman.ask import ask_goldman
    from goldman.decisions import decision_timeline
    from goldman.keyword_recall import keyword_recall
    from goldman.who import build_who_view, render_who
    from goldman_db.bank_accounts import BankAccountRepository
    from goldman_db.bills import BillRepository
    from goldman_db.clients import ClientRepository
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository
    from goldman_db.facts import FactRepository
    from goldman_db.tax_registrations import TaxRegistrationRepository
    from goldman_db.vendors import VendorRepository

    arguments = arguments or {}

    if name == "ask_goldman":
        question = (arguments.get("question") or "").strip()
        if not question:
            raise ValueError("question is required")
        entity = arguments.get("entity") or None
        if entity == "all":
            entity = None
        result = ask_goldman(
            question=question,
            channel_id=f"claude-ai-{arguments.get('channel_id', 'default')}",
            front_door="claude_code",
            entity_slug=entity,
        )
        return result["answer"]

    if name == "who":
        with app_conn() as conn:
            summaries = build_who_view(
                entities_repo=EntityRepository(conn),
                tax_repo=TaxRegistrationRepository(conn),
                bank_repo=BankAccountRepository(conn),
                clients_repo=ClientRepository(conn),
                vendors_repo=VendorRepository(conn),
                conn=conn,
            )
        return render_who(summaries)

    if name == "recall":
        question = (arguments.get("question") or "").strip()
        if not question:
            raise ValueError("question is required")
        entity = arguments.get("entity") or "all"
        top_n = int(arguments.get("top_n", 8))
        with app_conn() as conn:
            entity_id = None
            if entity not in ("all", ""):
                ent = EntityRepository(conn).get_by_slug(entity)
                if ent:
                    entity_id = ent.id
            results = keyword_recall(
                conn, query_text=question,
                entity_id=entity_id, top_n=top_n,
            )
        if not results:
            return f"No memory entries match: {question!r}."
        lines = [f"Top {len(results)} matches:"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. [{r.source_type}] :: {r.excerpt[:300]}")
        return "\n".join(lines)

    if name == "decisions":
        topic = (arguments.get("topic") or "").strip()
        if not topic:
            raise ValueError("topic is required")
        entity = arguments.get("entity")
        limit = int(arguments.get("limit", 20))
        with app_conn() as conn:
            rows = decision_timeline(
                conn=conn, topic=topic, entity_slug=entity, limit=limit,
            )
        if not rows:
            return f"No prior decisions matching {topic!r}."
        lines = [f"Decision timeline for {topic!r}:"]
        for r in rows:
            d = (r["created_at"] or "")[:10]
            ent = f" ({r['entity_slug']})" if r['entity_slug'] else ""
            lines.append(f"  {d}: {r['fact']}{ent}")
        return "\n".join(lines)

    if name == "remember":
        text = (arguments.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")
        kind = arguments.get("kind", "note")
        entity = (arguments.get("entity") or "amzg").lower()
        with app_conn() as conn:
            entity_id = None
            if entity != "global":
                ent = EntityRepository(conn).get_by_slug(entity)
                entity_id = ent.id if ent else None
            new_id = FactRepository(conn).upsert(
                entity_id=entity_id, kind=kind, fact=text,
                source="user_explicit",
            )
        return f"Recorded fact (id={new_id}, kind={kind}, entity={entity})."

    raise ValueError(f"Unknown tool: {name}")


def handle_mcp(*, headers: dict, raw_body: bytes) -> tuple:
    """Top-level MCP HTTP handler. Returns (status_code, response_body_dict_or_list_or_None).

    JSON-RPC 2.0 envelope. Responds with `{}` (or empty for notifications).
    """
    if not _is_authorized(headers):
        return 401, {
            "jsonrpc": "2.0", "id": None,
            "error": {"code": -32001, "message": "Unauthorized"},
        }

    try:
        msg = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception as e:
        return 400, _error(None, -32700, f"Parse error: {e}")

    # Batch requests not supported (rare in practice).
    if isinstance(msg, list):
        return 400, _error(None, -32600, "Batch requests not supported.")

    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params", {}) or {}

    # Notifications (no id) → return 202 with no body.
    is_notification = "id" not in msg

    try:
        if method == "initialize":
            response = _ok(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": SERVER_INFO,
                "instructions": (
                    "Goldman is the CFO agent for AMZ-Expert Global Limited "
                    "(HK) and Pacific Edge Outsourcing LLC (US). For free-form "
                    "questions prefer the ask_goldman tool — it routes through "
                    "Goldman's full Claude+tools+memory loop and returns "
                    "Goldman's own voice. Use the other tools (who, recall, "
                    "decisions, remember) when you need a specific structured "
                    "result."
                ),
            })
        elif method == "notifications/initialized":
            return 202, None
        elif method == "tools/list":
            response = _ok(req_id, {"tools": TOOLS})
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {}) or {}
            try:
                text = _run_tool(tool_name, arguments)
                response = _ok(req_id, {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                })
            except Exception as e:
                response = _ok(req_id, {
                    "content": [{"type": "text",
                                  "text": f"Tool error: {e}"}],
                    "isError": True,
                })
        elif method == "ping":
            response = _ok(req_id, {})
        else:
            response = _error(req_id, -32601, f"Method not found: {method}")
    except Exception as e:
        traceback.print_exc()
        return 500, _error(req_id, -32603, f"Internal error: {e}")

    if is_notification:
        return 202, None
    return 200, response
