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
    # ---- Phase 8: Gmail ----
    {
        "name": "search_emails",
        "description": "Search Liran's Gmail. Use Gmail search syntax: 'from:foo@bar.com subject:invoice after:2026/01/01'. Returns up to N message summaries.",
        "input_schema": {
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
        "description": "Open a Gmail thread end-to-end. Use after search_emails when you need the full body of a conversation.",
        "input_schema": {
            "type": "object",
            "properties": {"thread_id": {"type": "string"}},
            "required": ["thread_id"],
        },
    },
    {
        "name": "draft_email",
        "description": "Create a DRAFT in Liran's Gmail (he sends it himself). Use for proposed replies, payment reminders, vendor outreach. Pass thread_id to make it a reply, omit for a new email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "thread_id": {"type": "string", "description": "Optional — for reply drafts."},
                "in_reply_to_message_id": {"type": "string", "description": "Optional — for proper threading."},
            },
            "required": ["to", "subject", "body"],
        },
    },
    # ---- Phase 8: Drive ----
    {
        "name": "list_drive_folder",
        "description": "List files + subfolders directly under a Drive folder Goldman knows about. Default: lists the configured root (GOLDMAN_DRIVE_ROOT_FOLDER_ID). Pass folder_id to dive into a subfolder.",
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_id": {"type": "string", "description": "Optional. Omit to list the root."},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "read_drive_file",
        "description": "Read the contents of a Drive file Goldman uploaded. Returns text for text-shaped files; for binary, returns metadata + the webViewLink.",
        "input_schema": {
            "type": "object",
            "properties": {"file_id": {"type": "string"}},
            "required": ["file_id"],
        },
    },
    # ---- Phase 8/9: Zoho Books (per-entity, guardrailed) ----
    # HARD MAPPING — applied to every Zoho tool below:
    #   amzg = AMZ-Expert Global Limited (HK)     — Zoho org 876247837
    #   seo  = Pacific Edge Outsourcing LLC (US)  — Zoho org 914942331
    # Never confuse these. If a request doesn't unambiguously name the
    # company, REFUSE and ask which one. All writes require confirmed:true.
    {
        "name": "create_invoice",
        "description": (
            "Create a new invoice in Zoho Books. "
            "HARD MAPPING: amzg=AMZ-Expert Global Limited (HK, org 876247837), "
            "seo=Pacific Edge Outsourcing LLC (US Wyoming, org 914942331). "
            "WRITE OPERATION — first call returns a confirmation prompt; "
            "call again with confirmed:true to actually execute. NEVER pass "
            "confirmed:true on the first attempt; require explicit user 'yes'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "enum": ["amzg", "seo"]},
                "customer_id": {"type": "string"},
                "amount": {"type": "number"},
                "description": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."},
                "item_id": {"type": "string"},
                "confirmed": {"type": "boolean", "default": False,
                              "description": "Only set true AFTER showing the confirmation prompt to the user and getting their explicit 'yes'."},
            },
            "required": ["entity", "customer_id", "amount"],
        },
    },
    {
        "name": "list_customers",
        "description": (
            "List Zoho Books customers. HARD MAPPING: amzg=AMZ-Expert Global "
            "Limited (HK), seo=Pacific Edge Outsourcing LLC (US). Read-only; "
            "no confirmation needed. Result is stamped with [ENTITY:…]."
        ),
        "input_schema": {
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
            "Add a new customer in Zoho Books. HARD MAPPING: amzg=AMZ-Expert "
            "Global (HK), seo=Pacific Edge (US). WRITE OPERATION — first call "
            "returns a confirmation prompt; call again with confirmed:true."
        ),
        "input_schema": {
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
            "Record a bill/expense in Zoho Books. HARD MAPPING: amzg=AMZ-Expert "
            "Global (HK), seo=Pacific Edge (US). WRITE OPERATION — first call "
            "returns a confirmation prompt; call again with confirmed:true."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "enum": ["amzg", "seo"]},
                "amount": {"type": "number"},
                "currency": {"type": "string", "default": "USD"},
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
            "Email an existing Zoho invoice to its customer. IRREVERSIBLE — "
            "customer receives the email. HARD MAPPING: amzg=AMZ-Expert "
            "Global (HK), seo=Pacific Edge (US). WRITE OPERATION — first "
            "call returns a confirmation prompt; call again with confirmed:true."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "enum": ["amzg", "seo"]},
                "invoice_id": {"type": "string"},
                "confirmed": {"type": "boolean", "default": False},
            },
            "required": ["entity", "invoice_id"],
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
    # Phase 8: Gmail
    if name == "search_emails":
        return _search_emails(ctx, arguments)
    if name == "read_email_thread":
        return _read_email_thread(ctx, arguments)
    if name == "draft_email":
        return _draft_email(ctx, arguments)
    # Phase 8: Drive
    if name == "list_drive_folder":
        return _list_drive_folder(ctx, arguments)
    if name == "read_drive_file":
        return _read_drive_file(ctx, arguments)
    # Phase 8: Zoho
    if name == "create_invoice":
        return _create_invoice(ctx, arguments)
    if name == "list_customers":
        return _list_customers(ctx, arguments)
    if name == "create_customer":
        return _create_customer(ctx, arguments)
    if name == "create_expense":
        return _create_expense(ctx, arguments)
    if name == "send_invoice":
        return _send_invoice(ctx, arguments)
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
    # Phase 9: route through the guardrail so entity is banner-stamped + audited.
    # Take entity from explicit arg first, fall back to session.
    if "entity" not in args and ctx.entity_slug:
        args = {**args, "entity": ctx.entity_slug}

    def work(info):
        from goldman.zoho import invoice_service_for
        svc = invoice_service_for(
            info.slug, entity_repo=EntityRepository(ctx.conn),
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
    return _zoho_guardrail("list_invoices", ctx, args, work)


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


# =====================================================================
# Phase 8 — Gmail / Drive / Zoho agent tools
# =====================================================================

def _gmail_client():
    from goldman.gmail.client import GoldmanGmailClient
    return GoldmanGmailClient()


def _search_emails(ctx, args) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "search_emails error: empty query."
    limit = int(args.get("limit", 10))
    try:
        results = _gmail_client().search(query=query, limit=limit)
    except Exception as e:
        return f"Gmail unavailable: {e}"
    if not results:
        return f"No emails matched {query!r}."
    lines = [f"Top {len(results)} matches:"]
    for i, m in enumerate(results, 1):
        lines.append(
            f"{i}. [{m['date']}] {m['from']} — {m['subject']}\n"
            f"   thread_id={m['thread_id']}  preview: {m['snippet'][:140]}"
        )
    return "\n".join(lines)


def _read_email_thread(ctx, args) -> str:
    tid = (args.get("thread_id") or "").strip()
    if not tid:
        return "read_email_thread error: thread_id required."
    try:
        thread = _gmail_client().get_thread(thread_id=tid)
    except Exception as e:
        return f"Gmail unavailable: {e}"
    lines = [f"Thread {tid}:"]
    for m in thread["messages"]:
        body = m.get("body_text", "")[:1500]
        lines.append(
            f"\n--- {m['date']} | {m['from']} --- subject: {m['subject']}\n{body}"
        )
    return "\n".join(lines)


def _draft_email(ctx, args) -> str:
    to = (args.get("to") or "").strip()
    subject = (args.get("subject") or "").strip()
    body = args.get("body") or ""
    if not to or not subject or not body:
        return "draft_email error: to, subject, body all required."
    try:
        result = _gmail_client().create_draft_reply(
            thread_id=args.get("thread_id") or "",
            to=to, subject=subject, body=body,
            in_reply_to_message_id=args.get("in_reply_to_message_id"),
        )
    except Exception as e:
        return f"Gmail unavailable: {e}"
    return (
        f"Draft created. Open Gmail → Drafts to review + send.\n"
        f"  draft_id: {result['draft_id']}\n"
        f"  message_id: {result.get('message_id')}\n"
        f"  thread_id: {result.get('thread_id')}"
    )


# --- Drive ---

def _drive_client():
    import os
    from goldman.drive.client import GoogleDriveClient
    return GoogleDriveClient(), os.getenv("GOLDMAN_DRIVE_ROOT_FOLDER_ID", "")


def _list_drive_folder(ctx, args) -> str:
    folder_id = (args.get("folder_id") or "").strip()
    limit = int(args.get("limit", 50))
    try:
        client, root = _drive_client()
        target = folder_id or root
        if not target:
            return "Drive unavailable: no folder_id and no root folder configured."
        files = client.list_children(parent_id=target, limit=limit)
    except Exception as e:
        return f"Drive unavailable: {e}"
    if not files:
        return "(empty folder)"
    lines = [f"{len(files)} item(s):"]
    for f in files:
        icon = "📁" if f.get("mimeType") == "application/vnd.google-apps.folder" else "📄"
        size = f" ({int(f['size']):,}b)" if f.get("size") else ""
        lines.append(f"  {icon} {f['name']}{size}  id={f['id']}")
    return "\n".join(lines)


def _read_drive_file(ctx, args) -> str:
    file_id = (args.get("file_id") or "").strip()
    if not file_id:
        return "read_drive_file error: file_id required."
    try:
        client, _ = _drive_client()
        meta = client.get_file_metadata(file_id=file_id)
        mime = meta.get("mimeType", "")
        if mime == "application/vnd.google-apps.folder":
            return f"That is a folder, not a file. Use list_drive_folder with folder_id={file_id}."
        # Text-shaped files: download + decode.
        TEXTY = ("text/", "application/json", "application/xml")
        if mime.startswith(TEXTY) or any(mime.startswith(t) for t in TEXTY):
            data = client.download_file_bytes(file_id=file_id)
            return f"{meta['name']} ({mime}):\n{data.decode('utf-8', errors='replace')[:4000]}"
        # Binary — return metadata + view link.
        return (
            f"{meta['name']} — {mime}\n"
            f"Size: {meta.get('size', 'unknown')} bytes\n"
            f"Modified: {meta.get('modifiedTime', '?')}\n"
            f"Open: {meta.get('webViewLink', '(no link)')}"
        )
    except Exception as e:
        return f"Drive unavailable: {e}"


# --- Zoho Books ---

def _zoho_services_for(ctx, entity_slug: str):
    """Return (invoice_svc, contact_svc, item_svc, expense_svc) or raise."""
    from goldman.zoho import (
        invoice_service_for, contact_service_for,
        item_service_for, expense_service_for,
    )
    repo = EntityRepository(ctx.conn)
    inv = invoice_service_for(entity_slug, entity_repo=repo)
    contact = contact_service_for(entity_slug, entity_repo=repo)
    item = item_service_for(entity_slug, entity_repo=repo)
    expense = expense_service_for(entity_slug, entity_repo=repo)
    return inv, contact, item, expense


def _zoho_guardrail(tool_name: str, ctx, args: dict, work):
    """Wrap a Zoho tool with the Phase 9 safety guardrail.

    1. Resolve the entity (refuses if slug missing / unknown / no Zoho).
    2. Block writes that aren't confirmed.
    3. Run the underlying work.
    4. Prefix with the entity banner.
    5. Audit log every call (executed or blocked).
    """
    from goldman.zoho_safety import (
        resolve_entity, banner, needs_confirmation,
        confirmation_prompt, log_audit, log_blocked_no_entity,
        UnknownEntityError,
    )
    channel_id = getattr(ctx, "chat_id", "") or ""
    try:
        info = resolve_entity(ctx.conn, args.get("entity") or "")
    except UnknownEntityError as e:
        log_blocked_no_entity(
            ctx.conn, tool_name=tool_name, arguments=args,
            reason=str(e), channel_id=channel_id,
        )
        return (
            f"⚠️  Zoho call refused — {e}.\n"
            f"Specify exactly which company: 'amzg' = AMZ-Expert Global "
            f"Limited (HK), 'seo' = Pacific Edge Outsourcing LLC (US, WY)."
        )

    if needs_confirmation(tool_name, args):
        prompt = confirmation_prompt(info, tool_name, args)
        log_audit(
            ctx.conn, info=info, tool_name=tool_name, arguments=args,
            status="blocked_unconfirmed",
            result_summary="awaiting confirmation",
            channel_id=channel_id,
        )
        return prompt

    try:
        body = work(info)
        log_audit(
            ctx.conn, info=info, tool_name=tool_name, arguments=args,
            status="executed", result_summary=body[:500],
            channel_id=channel_id,
        )
        return f"{banner(info)}\n{body}"
    except Exception as e:
        msg = f"Zoho {tool_name} failed: {e}"
        log_audit(
            ctx.conn, info=info, tool_name=tool_name, arguments=args,
            status="error", result_summary=str(e)[:500],
            channel_id=channel_id,
        )
        return f"{banner(info)}\n{msg}"


def _create_invoice(ctx, args) -> str:
    customer_id = args.get("customer_id")
    amount = args.get("amount")
    if not customer_id or amount is None:
        return "create_invoice error: customer_id and amount are required."

    def work(info):
        inv_svc, _, _, _ = _zoho_services_for(ctx, info.slug)
        line_items = [{
            "rate": float(amount), "quantity": 1,
            "description": args.get("description") or "",
        }]
        if args.get("item_id"):
            line_items[0]["item_id"] = args["item_id"]
        invoice = inv_svc.create_invoice(
            customer_id=customer_id,
            line_items=line_items,
            date=args.get("date", ""),
        )
        return (
            f"Created invoice {invoice.invoice_number} for "
            f"{invoice.customer_name} — total {invoice.total} {invoice.currency_code or ''}."
        )
    return _zoho_guardrail("create_invoice", ctx, args, work)


def _list_customers(ctx, args) -> str:
    limit = int(args.get("limit", 50))

    def work(info):
        _, contact_svc, _, _ = _zoho_services_for(ctx, info.slug)
        contacts = contact_svc.list_contacts(per_page=min(limit, 200))
        if not contacts:
            return f"No customers found."
        lines = [f"{len(contacts)} customer(s):"]
        for c in contacts[:limit]:
            lines.append(f"  {c.contact_id} | {c.contact_name} | {c.email}")
        return "\n".join(lines)
    return _zoho_guardrail("list_customers", ctx, args, work)


def _create_customer(ctx, args) -> str:
    name = (args.get("name") or "").strip()
    if not name:
        return "create_customer error: name is required."

    def work(info):
        _, contact_svc, _, _ = _zoho_services_for(ctx, info.slug)
        contact = contact_svc.create_contact(
            contact_name=name,
            company_name=args.get("company", ""),
            email=args.get("email", ""),
            phone=args.get("phone", ""),
        )
        return f"Created customer {contact.contact_id} — {contact.contact_name} ({contact.email})."
    return _zoho_guardrail("create_customer", ctx, args, work)


def _create_expense(ctx, args) -> str:
    amount = args.get("amount")
    if amount is None:
        return "create_expense error: amount is required."

    def work(info):
        _, _, _, expense_svc = _zoho_services_for(ctx, info.slug)
        if not expense_svc:
            return "create_expense not yet supported in this build."
        result = expense_svc.create_expense(
            amount=float(amount),
            date=args.get("date", ""),
            description=args.get("description", ""),
            vendor_id=args.get("vendor_id", ""),
            account_id=args.get("account_id", ""),
            currency_code=args.get("currency", "USD"),
        )
        return f"Recorded expense {result.expense_id} ({amount} {args.get('currency', 'USD')})."
    return _zoho_guardrail("create_expense", ctx, args, work)


def _send_invoice(ctx, args) -> str:
    invoice_id = (args.get("invoice_id") or "").strip()
    if not invoice_id:
        return "send_invoice error: invoice_id is required."

    def work(info):
        inv_svc, _, _, _ = _zoho_services_for(ctx, info.slug)
        ok = inv_svc.send_invoice(invoice_id)
        return (
            f"Sent invoice {invoice_id} ✓" if ok
            else f"Zoho rejected the send request for invoice {invoice_id}."
        )
    return _zoho_guardrail("send_invoice", ctx, args, work)
