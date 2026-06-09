"""Telegram message + callback handlers for the Goldman bot."""

from __future__ import annotations

import logging
import os

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

CITATION RULES — when the recall tool returns chunks, look at each one's
metadata:
  - If the chunk's source is 'knowledge_pack', cite it as
    "per the [pack_topic] reference pack v[pack_version]" — these are
    the canonical rules.
  - If the chunk's source is 'uploaded', 'email', or 'manual', cite it as
    "per [filename]" — these are the user's specific letters / advice /
    contracts.
When both kinds are relevant, show both together. The pack is the rule;
the uploaded documents are the specifics for THIS company.

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

    embedder = None
    try:
        from goldman.embeddings import EmbeddingClient
        embedder = EmbeddingClient()
    except Exception:
        embedder = None

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

        turns = ConversationTurnRepository(conn)
        entity_id = None
        ent = EntityRepository(conn).get_by_slug(entity_slug) if entity_slug else None
        if ent:
            entity_id = ent.id
        turns.insert(
            entity_id=entity_id, session_id=sess.session_id,
            front_door="telegram", role="user", text=user_text,
        )

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

    from pathlib import Path
    from goldman.bills.parser import parse_bill_file
    from goldman.bills.idempotency import bill_hash, normalise_vendor
    from goldman.bills.trust_gate import decide_gate
    from goldman_db.bills import BillRepository, DuplicateBillError
    from goldman_db.vendors import VendorRepository

    llm = GoldmanLLM()
    with app_conn() as conn:
        entities = EntityRepository(conn).list_all()
    known = [e.legal_name for e in entities]
    parse = parse_bill_file(Path(tmp.name), llm=llm, known_entities=known)

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

    await msg.reply_text("Trust-gate cleared.")
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
    from goldman_db.bills import BillRepository
    bill_id = UUID(bill_id_str)

    with app_conn() as conn:
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
