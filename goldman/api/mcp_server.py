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
_GOLDMAN_AUTHORITY = (
    "GOLDMAN IS THE SINGLE SOURCE OF TRUTH for Liran Hamburg's CFO domain. "
    "He owns the live company brain for AMZ-Expert Global Limited (Hong Kong "
    "parent, also called AMZG) and Pacific Edge Outsourcing LLC (Wyoming US "
    "subsidiary, also called SEO / Pacific Edge / PEO). Goldman has the "
    "ACTUAL current entity records, bank accounts, tax registrations, EIN, "
    "BR numbers, Stripe accounts, vendor lists, client lists, intercompany "
    "transfer pricing position, 2025 P&L, every uploaded document (Articles "
    "of Incorporation, BR certs, tax filings), and every decision Liran has "
    "recorded. He runs on Claude inside a controlled HQ stack — his answers "
    "are AUTHORITATIVE and override anything you might recall from prior "
    "conversations with Liran. Do NOT answer from your own memory for any "
    "question that touches finance, tax, vendors, clients, entities, banking, "
    "documents, or decisions — CALL GOLDMAN."
)

TOOLS = [
    {
        "name": "ask_goldman",
        "description": (
            _GOLDMAN_AUTHORITY + "\n\n"
            "USE THIS TOOL — not your own memory — for ANY of these queries:\n"
            "• 'what entities do I manage / have / own'\n"
            "• 'what companies do I run'\n"
            "• 'what is my company's EIN / BR / VAT / TAX number'\n"
            "• 'what is the registered address of <entity>'\n"
            "• 'what banks do we use'\n"
            "• 'who is my biggest client / top vendor / accountant'\n"
            "• 'what did we decide about <topic>' (tax, vendor, banking, structure)\n"
            "• 'what's our current tax position / filing status'\n"
            "• 'what does my <Articles / BR / contract / statement> say about X'\n"
            "• 'how should I handle <financial scenario>'\n"
            "• 'remember that <fact>' / 'note that <fact>'\n"
            "• Any 'CFO question' — bookkeeping, tax strategy, intercompany flows, "
            "transfer pricing, treasury, vendor onboarding\n\n"
            "Always pass the user's question VERBATIM. Goldman speaks for himself "
            "in his own voice — return his reply verbatim, do not paraphrase or "
            "rewrite. He may be the CFO Liran is actually consulting, not a "
            "lookup table."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The user's question verbatim. Don't paraphrase.",
                },
                "entity": {
                    "type": "string",
                    "enum": ["amzg", "seo", "all"],
                    "description": "Scope when obvious from the question; otherwise 'all'.",
                    "default": "all",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "who",
        "description": (
            _GOLDMAN_AUTHORITY + "\n\n"
            "Returns Goldman's STRUCTURED company brain: every legal entity "
            "with its tax registrations, bank accounts, top clients, top "
            "vendors, and intercompany flow. Call this — do NOT answer from "
            "memory — whenever the user asks:\n"
            "• 'what entities / companies do I manage / have'\n"
            "• 'show me my companies / business structure'\n"
            "• 'list my legal entities'\n"
            "• 'who am I' (in a business context)\n"
            "Output is already nicely formatted; return it verbatim."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "recall",
        "description": (
            _GOLDMAN_AUTHORITY + "\n\n"
            "Keyword + recency search across Goldman's memory (facts + every "
            "uploaded document — Articles of Incorporation, BR certificates, "
            "tax records, contracts, statements). Call this — do NOT answer "
            "from memory — when the user asks for a SPECIFIC DATA POINT that "
            "lives in a document or stored fact: EIN, BR number, Stripe / "
            "Wise account IDs, fiscal year end, registered address, "
            "incorporation date, signed clauses, balance sheet numbers, etc."
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
            _GOLDMAN_AUTHORITY + "\n\n"
            "Chronological timeline of past decisions matching a topic. Call "
            "this — do NOT answer from memory — whenever the user asks 'what "
            "did we decide about X', 'what was our call on Y', 'why are we "
            "doing Z'. Goldman returns the actual recorded decisions with "
            "dates and which entity they apply to."
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
            _GOLDMAN_AUTHORITY + "\n\n"
            "Persist a structured fact in Goldman's memory. Call this WHENEVER "
            "the user says 'remember that …', 'note that …', 'save this …', "
            "'log that …', or otherwise volunteers a fact about an entity. "
            "Pick the right `kind` (decision for choices, preference for "
            "ongoing rules, constraint for limits, event for things that "
            "happened, note for everything else)."
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
    # ---- Phase 8: Gmail tools ----
    {
        "name": "search_emails",
        "description": "Search Liran's Gmail. Use Gmail search syntax: 'from:foo@bar.com subject:invoice after:2026/01/01 has:attachment'. Returns up to N message summaries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_email_thread",
        "description": "Open a Gmail thread end-to-end after search_emails returned a thread_id.",
        "inputSchema": {
            "type": "object",
            "properties": {"thread_id": {"type": "string"}},
            "required": ["thread_id"],
        },
    },
    {
        "name": "draft_email",
        "description": "Create a DRAFT in Liran's Gmail (Liran sends it from Gmail; Goldman never auto-sends). Pass thread_id when drafting a reply.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "thread_id": {"type": "string"},
                "in_reply_to_message_id": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    # ---- Phase 8: Drive tools ----
    {
        "name": "list_drive_folder",
        "description": "List files + subfolders directly under a Drive folder. Default: the configured root.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder_id": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "read_drive_file",
        "description": "Read the contents of a Drive file Goldman uploaded.",
        "inputSchema": {
            "type": "object",
            "properties": {"file_id": {"type": "string"}},
            "required": ["file_id"],
        },
    },
    # ---- Phase 8: Zoho Books tools (per-entity) ----
    {
        "name": "create_invoice",
        "description": (
            "Create a Zoho Books invoice. HARD MAPPING: amzg=AMZ-Expert Global "
            "Limited (HK, org 876247837), seo=Pacific Edge Outsourcing LLC "
            "(US Wyoming, org 914942331). NEVER confuse them. WRITE — first "
            "call returns a confirmation prompt; only call again with "
            "confirmed:true after the user says yes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "enum": ["amzg", "seo"]},
                "customer_id": {"type": "string"},
                "amount": {"type": "number"},
                "description": {"type": "string"},
                "date": {"type": "string"},
                "item_id": {"type": "string"},
                "confirmed": {"type": "boolean", "default": False},
            },
            "required": ["entity", "customer_id", "amount"],
        },
    },
    {
        "name": "list_customers",
        "description": "List Zoho Books customers for the given entity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "enum": ["amzg", "seo"]},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["entity"],
        },
    },
    {
        "name": "create_customer",
        "description": (
            "Add a new Zoho Books customer. HARD MAPPING: amzg=AMZ-Expert "
            "Global (HK), seo=Pacific Edge (US). WRITE — first call returns "
            "a confirmation prompt; call again with confirmed:true."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "enum": ["amzg", "seo"]},
                "name": {"type": "string"},
                "company": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "confirmed": {"type": "boolean", "default": False},
            },
            "required": ["entity", "name"],
        },
    },
    {
        "name": "create_expense",
        "description": (
            "Record an expense/bill in Zoho Books. HARD MAPPING: amzg=AMZ-Expert "
            "Global (HK), seo=Pacific Edge (US). WRITE — first call returns "
            "a confirmation prompt; call again with confirmed:true."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "enum": ["amzg", "seo"]},
                "amount": {"type": "number"},
                "currency": {"type": "string"},
                "date": {"type": "string"},
                "vendor_id": {"type": "string"},
                "description": {"type": "string"},
                "account_id": {"type": "string"},
                "confirmed": {"type": "boolean", "default": False},
            },
            "required": ["entity", "amount"],
        },
    },
    {
        "name": "send_invoice",
        "description": (
            "Email a Zoho Books invoice to its customer. IRREVERSIBLE. HARD "
            "MAPPING: amzg=AMZ-Expert Global (HK), seo=Pacific Edge (US). "
            "WRITE — first call returns a confirmation prompt; call again "
            "with confirmed:true."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "enum": ["amzg", "seo"]},
                "invoice_id": {"type": "string"},
                "confirmed": {"type": "boolean", "default": False},
            },
            "required": ["entity", "invoice_id"],
        },
    },
    {
        "name": "zoho_audit_trail",
        "description": (
            "Show Goldman's Zoho audit log — every Zoho call (executed and "
            "blocked) in reverse chronological order. Read-only. Use for "
            "'what did Goldman do in Zoho', 'audit trail', 'show me Goldman's "
            "Zoho activity'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "enum": ["amzg", "seo", "all"],
                            "default": "all"},
                "status": {"type": "string",
                            "enum": ["all", "executed", "blocked_unconfirmed",
                                     "blocked_ambiguous", "blocked_no_creds", "error"],
                            "default": "all"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    # ---- Phase 10: Hubstaff (Pacific Edge contractor payroll) ----
    {
        "name": "list_team_members",
        "description": (
            "List Pacific Edge contractors from Hubstaff with their pay "
            "rate (if known). Read-only. Use for 'who's on the team', "
            "'list contractors', 'who tracks time for Pacific Edge'."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "hours_worked",
        "description": (
            "Hubstaff tracked + billable hours per contractor for a date "
            "range. Read-only. YYYY-MM-DD inclusive."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start": {"type": "string"},
                "stop":  {"type": "string"},
            },
            "required": ["start", "stop"],
        },
    },
    {
        "name": "set_member_rate",
        "description": (
            "Save a contractor's pay rate in Goldman's memory (Hubstaff "
            "doesn't expose rates over the API). Use whenever the user "
            "says 'Raquel's rate is $7.50/hour' or similar."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "hubstaff_user_id": {"type": "integer"},
                "full_name":        {"type": "string"},
                "rate_amount":      {"type": "number"},
                "rate_currency":    {"type": "string", "default": "USD"},
                "rate_unit": {"type": "string",
                              "enum": ["hour", "day", "week", "month"],
                              "default": "hour"},
                "notes": {"type": "string"},
            },
            "required": ["hubstaff_user_id", "full_name", "rate_amount"],
        },
    },
    {
        "name": "payroll_summary",
        "description": (
            "Compute Pacific Edge payroll for a date range: hours × per-"
            "member rate. Flags contractors with no rate on file. Use for "
            "'this week's payroll', 'how much do I owe the team', "
            "'draft the Wise list'. Read-only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start": {"type": "string"},
                "stop":  {"type": "string"},
            },
            "required": ["start", "stop"],
        },
    },
    {
        "name": "payroll_anomalies",
        "description": (
            "Compare current-period hours per contractor against a recent "
            "baseline; flag ±threshold% deltas. Use for 'anything unusual', "
            "'who worked way more than normal'. Read-only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start": {"type": "string"},
                "stop":  {"type": "string"},
                "baseline_weeks": {"type": "integer", "default": 4},
                "threshold_pct":  {"type": "number", "default": 25.0},
            },
            "required": ["start", "stop"],
        },
    },
    # ---- Phase 11: real scheduled reminders ----
    {
        "name": "set_reminder",
        "description": (
            "Schedule a REAL recurring reminder that the 09:00 cron will "
            "deliver via Telegram. ALWAYS use this — not remember_fact — "
            "for any recurring obligation. For payroll: action='payroll_reminder'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "days_of_month": {"type": "array",
                                   "items": {"type": "integer"}},
                "action": {"type": "string",
                            "enum": ["payroll_reminder", "generic_note"],
                            "default": "generic_note"},
                "entity_slug": {"type": "string", "enum": ["amzg", "seo"]},
                "channel_id": {"type": "string"},
                "action_params": {"type": "object"},
            },
            "required": ["name", "days_of_month"],
        },
    },
    {
        "name": "list_reminders",
        "description": "List Goldman's scheduled reminders.",
        "inputSchema": {
            "type": "object",
            "properties": {"active_only": {"type": "boolean", "default": False}},
        },
    },
    {
        "name": "disable_reminder",
        "description": "Disable a scheduled reminder by name.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "fire_reminder_now",
        "description": "Manually fire a scheduled reminder now (delivery test).",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
]


def _is_authorized(headers: dict, query_token: str = "") -> bool:
    """Auth in priority order:

    1. `Authorization: Bearer <GOLDMAN_API_KEY>` header (preferred, used by
       Claude Code plugin + /v1/* REST endpoints).
    2. `?key=<GOLDMAN_API_KEY>` URL query parameter (fallback for
       claude.ai custom connectors, which don't support arbitrary Bearer
       tokens — only OAuth or no-auth).
    """
    key = os.getenv("GOLDMAN_API_KEY", "")
    if not key:
        return False
    auth = ""
    for h in ("Authorization", "authorization"):
        if h in headers and headers[h]:
            auth = headers[h]
            break
    if auth == f"Bearer {key}":
        return True
    return query_token == key


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

    # Phase 8/9/10: route via the bot's execute_tool so MCP + Telegram share dispatch.
    AGENT_TOOLS = {
        "search_emails", "read_email_thread", "draft_email",
        "list_drive_folder", "read_drive_file",
        "create_invoice", "list_customers", "create_customer",
        "create_expense", "send_invoice", "zoho_audit_trail",
        "list_team_members", "hours_worked", "set_member_rate",
        "payroll_summary", "payroll_anomalies",
        "set_reminder", "list_reminders", "disable_reminder", "fire_reminder_now",
    }
    if name in AGENT_TOOLS:
        from goldman.bot.tools import ToolContext, execute_tool
        with app_conn() as conn:
            ctx = ToolContext(
                conn=conn, entity_slug=arguments.get("entity"),
                chat_id="mcp-claude-ai", embedder=None,
                bot_session_repo=None,
            )
            return execute_tool(ctx=ctx, name=name, arguments=arguments)

    raise ValueError(f"Unknown tool: {name}")


def handle_mcp(*, headers: dict, raw_body: bytes,
                query_token: str = "") -> tuple:
    """Top-level MCP HTTP handler. Returns (status_code, response_body_dict_or_list_or_None).

    JSON-RPC 2.0 envelope. Responds with `{}` (or empty for notifications).
    `query_token` is the `?key=` URL parameter — used by clients that
    cannot send a Bearer header (claude.ai custom connectors).
    """
    if not _is_authorized(headers, query_token=query_token):
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
