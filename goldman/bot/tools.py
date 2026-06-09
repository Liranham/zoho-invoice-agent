"""Goldman tool registry.

TOOL_SCHEMAS define what Claude can call. execute_tool dispatches and
returns a text result Claude can read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from goldman_db.entities import EntityRepository
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
