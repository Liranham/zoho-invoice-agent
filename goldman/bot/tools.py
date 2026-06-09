"""Goldman tool registry.

TOOL_SCHEMAS define what Claude can call. execute_tool dispatches and
returns a text result Claude can read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from goldman.decisions import decision_timeline
from goldman_db.entities import EntityRepository
from goldman.keyword_recall import keyword_recall


TOOL_SCHEMAS = [
    {
        "name": "recall",
        "description": "Search Goldman's memory (facts + uploaded documents) for relevant context. Use when the user asks about prior decisions, advice, contract clauses, EIN/BR numbers, addresses, or anything that might live in an uploaded document. By default searches BOTH entities; pass entity='amzg' or entity='seo' only when you want to scope to one company.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The query in natural language."},
                "entity": {"type": "string", "enum": ["amzg", "seo", "all"],
                            "description": "Which entity to scope to. Default 'all' = search across both companies.",
                            "default": "all"},
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
    if name == "recall_decisions":
        return _recall_decisions(ctx, arguments)
    raise ValueError(f"Unknown tool: {name}")


def _recall(ctx, args) -> str:
    question = args["question"]
    top_n = int(args.get("top_n", 8))
    requested_entity = (args.get("entity") or "all").lower()

    entity_id = None
    if requested_entity not in ("all", ""):
        ent = EntityRepository(ctx.conn).get_by_slug(requested_entity)
        if ent:
            entity_id = ent.id

    results = keyword_recall(
        ctx.conn, query_text=question,
        entity_id=entity_id, top_n=top_n,
    )
    if not results:
        return f"No memory entries match: {question!r}."
    lines = [f"Top {len(results)} matches:"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. [{r.source_type}] score={r.score:.1f} :: {r.excerpt[:200]}")
    return "\n".join(lines)


def _who(ctx) -> str:
    from goldman.who import build_who_view, render_who
    from goldman_db.bank_accounts import BankAccountRepository
    from goldman_db.clients import ClientRepository
    from goldman_db.tax_registrations import TaxRegistrationRepository
    from goldman_db.vendors import VendorRepository

    summaries = build_who_view(
        entities_repo=EntityRepository(ctx.conn),
        tax_repo=TaxRegistrationRepository(ctx.conn),
        bank_repo=BankAccountRepository(ctx.conn),
        clients_repo=ClientRepository(ctx.conn),
        vendors_repo=VendorRepository(ctx.conn),
        conn=ctx.conn,
    )
    return render_who(summaries)


def _remember_fact(ctx, args) -> str:
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
    ent = EntityRepository(ctx.conn).get_by_slug(slug)
    if not ent:
        return f"Unknown entity slug: {slug}."
    ctx.bot_session_repo.set_current_entity(
        "telegram", ctx.chat_id, slug,
    )
    ctx.entity_slug = slug
    return f"Switched to {ent.legal_name} ({slug})."


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
