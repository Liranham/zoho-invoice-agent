"""Telegram message + callback handlers for the Goldman bot."""

from __future__ import annotations

import logging
import os
import re
import time

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
from utils.telegram_format import telegram_format


async def _reply_html(message, text: str, **kwargs):
    """Send a reply through the Telegram HTML pipeline so the LLM's
    markdown (`**bold**`, `# Heading`, `|---|---|`, `[label](url)`)
    renders as actual formatting instead of arriving as literal characters
    in the Telegram client.

    Every outbound message from Goldman goes through this — single source
    of truth for Telegram formatting, mirrors the same pattern in Bob
    (ai-personal-assistant/telegram_bot/bot.py) and the Slack composer
    (amz-expert-hq-hub/supabase/functions/_shared/slack-format.ts).
    """
    formatted = telegram_format(text or "")
    return await message.reply_text(
        formatted or "(empty reply)",
        parse_mode="HTML",
        **kwargs,
    )

logger = logging.getLogger(__name__)


# A document we received but couldn't auto-file, kept briefly per chat so a
# follow-up message ("it's Pacific Edge, save it to Drive") can be linked back
# to the file the user just uploaded. In-memory is fine: single bot instance,
# and a lost pending doc after a restart just means the user re-sends.
_PENDING_DOCS: dict[int, dict] = {}
_PENDING_TTL_SECONDS = 15 * 60

# The last file we successfully read for a chat, kept briefly so a follow-up
# question ("what do you make of it?") is answered against the file instead of
# being treated as an unrelated message. {chat_id: {filename, text, ts, consumed}}
_RECENT_DOCS: dict[int, dict] = {}

_QUESTION_HINTS = (
    "what", "how", "why", "should", "do you", "can you", "explain",
    "understand", "make of", "review", "analy", "zoho", "summar",
    "tell me", "is it", "are these", "advice", "think", "mean", "need to",
)


def _looks_like_question(text: str) -> bool:
    """True if the text is a real question/instruction rather than a bare label
    (like just a company name). Used to decide whether an attached file should
    be answered, not merely filed."""
    if not text:
        return False
    t = text.strip().lower()
    if "?" in t:
        return True
    if any(k in t for k in _QUESTION_HINTS):
        return True
    return len(t.split()) > 4


def _entity_from_text(text: str, entities: list):
    """Best-effort: figure out which entity the user named in free text.

    Matches on the entity slug ('amzg'/'seo'), the full legal name, or any
    two consecutive distinctive words of the legal name (so "Pacific Edge"
    resolves to Pacific Edge Outsourcing LLC). Returns a slug or None.
    """
    if not text:
        return None
    low = text.lower()
    # Explicit nicknames the user actually uses for each company.
    aliases = {
        "seo": ["pacific edge", "pacific-edge", "peo", "us llc", "wyoming"],
        "amzg": ["amz-expert global", "amz expert global", "amzg", "hong kong", "hk company"],
    }
    for e in entities:
        if not e.slug:
            continue
        if e.slug.lower() in low:
            return e.slug
        for alias in aliases.get(e.slug.lower(), []):
            if alias in low:
                return e.slug
        name = (e.legal_name or "").lower()
        if name and name in low:
            return e.slug
        words = [w for w in re.split(r"[^a-z0-9]+", name) if len(w) > 2]
        for i in range(len(words) - 1):
            if f"{words[i]} {words[i + 1]}" in low:
                return e.slug
    return None


def _classify_entity(*, tmp_path: str, entities: list, llm, hint: str = "") -> tuple:
    """Ask Claude to pick which entity a non-bill document belongs to.

    Returns (entity_slug, category, confidence). entity_slug may be None
    if Claude can't tell, in which case Telegram asks the user.
    Category is one of: 'Documents', 'Tax', 'Statements', 'Contracts'.
    """
    schema = {
        "type": "object",
        "properties": {
            "entity_slug": {
                "type": "string",
                "enum": [e.slug for e in entities] + ["unknown"],
                "description": "Which company this document belongs to.",
            },
            "category": {
                "type": "string",
                "enum": ["Documents", "Tax", "Statements", "Contracts"],
                "description": "Best-fit folder category.",
            },
            "reason": {"type": "string"},
        },
        "required": ["entity_slug", "category"],
    }
    legal_names = "; ".join(f"{e.slug}={e.legal_name}" for e in entities)
    hint_line = (
        f" The user said this when sending the file: \"{hint.strip()}\". "
        f"Trust that strongly when deciding the company."
        if hint and hint.strip() else ""
    )
    system = (
        f"You read a document and decide which company it belongs to. "
        f"Companies: {legal_names}.{hint_line} If you cannot tell with high "
        f"confidence, return 'unknown'. Pick a sensible category: Tax for "
        f"filings/IRS/HKIRD letters, Statements for bank/Stripe/Wise "
        f"statements, Contracts for signed agreements, Documents for "
        f"everything else."
    )
    try:
        result = llm.extract_from_document(
            document_path=tmp_path, system=system,
            tool_name="classify_document", tool_schema=schema,
        )
    except Exception as e:
        logger.exception("Classification failed: %s", e)
        return None, "Documents", 0.0

    slug = result.get("entity_slug")
    if slug == "unknown":
        slug = None
    return slug, result.get("category", "Documents"), 1.0


async def _intake_general_document(*, update, tmp_path, original_filename,
                                    entities, llm, caption: str = "",
                                    force_entity_slug=None) -> None:
    """Ingest a non-bill document: classify entity, upload to memory + Drive.

    caption           — any text the user sent with the file (Telegram caption
                        or a follow-up message); used to identify the company.
    force_entity_slug — caller already knows the company (e.g. the user just
                        named it in a reply); skip guessing.
    """
    msg = update.message
    # Identify the company in priority order: explicit caller > what the user
    # typed > reading the file itself.
    classified_slug, category, _ = _classify_entity(
        tmp_path=tmp_path, entities=entities, llm=llm, hint=caption,
    )
    entity_slug = (
        force_entity_slug
        or _entity_from_text(caption, entities)
        or classified_slug
    )

    if entity_slug is None:
        # Hold the file so a follow-up ("it's Pacific Edge") can finish the job.
        _PENDING_DOCS[update.effective_chat.id] = {
            "tmp_path": tmp_path,
            "original_filename": original_filename,
            "caption": caption,
            "ts": time.time(),
        }
        await _reply_html(
            msg,
            f"Got **{original_filename}** — I couldn't tell which company "
            f"it's for. Just reply with the company name (e.g. **Pacific "
            f"Edge** or **AMZ-Expert Global**) and I'll file it.",
        )
        return

    # Filing now — drop any stale pending entry for this chat.
    _PENDING_DOCS.pop(update.effective_chat.id, None)

    ent = next(e for e in entities if e.slug == entity_slug)

    from pathlib import Path
    from goldman.documents import upload_document
    from goldman.llm import DocumentSummariser
    from goldman.storage import SupabaseStorage
    from goldman_db.documents import DocumentChunkRepository, DocumentRepository

    storage = SupabaseStorage()
    summariser = DocumentSummariser()
    drive_client = None
    try:
        from goldman.drive.client import GoogleDriveClient
        drive_client = GoogleDriveClient()
    except Exception:
        pass

    target = Path(tmp_path)
    if original_filename and target.name != original_filename:
        renamed = target.parent / original_filename
        try:
            target.rename(renamed)
            target = renamed
        except Exception:
            pass

    with app_conn() as conn:
        doc_repo = DocumentRepository(conn)
        chunk_repo = DocumentChunkRepository(conn)
        result = upload_document(
            file_path=target,
            entity_id=ent.id,
            entity_slug=ent.slug,
            storage=storage,
            doc_repo=doc_repo,
            chunk_repo=chunk_repo,
            summariser=summariser,
            bucket="goldman-documents",
            drive_client=drive_client,
            drive_root_id=os.getenv("GOLDMAN_DRIVE_ROOT_FOLDER_ID") or None,
            entity_legal_name=ent.legal_name,
            drive_category=category,
        )

    # Pull the file's text so we can (a) answer a question asked with it, and
    # (b) keep it on hand for an immediate follow-up question.
    doc_text = ""
    try:
        import mimetypes
        from goldman.documents import _read_text
        mt, _ = mimetypes.guess_type(target.name)
        doc_text = _read_text(target, mt or "application/octet-stream") or ""
    except Exception:
        logger.exception("Could not extract text from %s", target)

    _RECENT_DOCS[update.effective_chat.id] = {
        "filename": original_filename, "text": doc_text,
        "ts": time.time(), "consumed": False,
    }

    filed_line = (
        f"📁 Filed **{original_filename}** under "
        f"**{ent.legal_name} / {category}** "
        f"({result.chunk_count} chunk(s) indexed)."
    )

    # If the user attached the file AND asked something, ANSWER it — don't just
    # file and walk away. This is the whole point: a file is context for the
    # conversation, not a dead-drop.
    if _looks_like_question(caption) and doc_text.strip():
        _RECENT_DOCS[update.effective_chat.id]["consumed"] = True
        await _reply_html(msg, filed_line)
        await _run_goldman_reply(
            update, update.effective_chat.id, llm, caption,
            doc_context={"filename": original_filename, "text": doc_text},
        )
    else:
        await _reply_html(msg, filed_line + "\n\nAsk me anything about it.")


GOLDMAN_PERSONA = """\
You are Goldman, the CFO of AMZ-Expert Global Limited (Hong Kong parent)
and Pacific Edge Outsourcing LLC (US Wyoming subsidiary). You speak in
clear plain English, no jargon. You are conservative, precise, and never
fabricate. When you don't know, you say so. When you act, you cite the
source (which Zoho org, which document, which prior conversation).

BIAS TO ACTION (read this — Liran gets frustrated by over-asking):
- When Liran sends a file or screenshot and asks "what do you make of it?"
  or "what do we need to do?", READ it and give him a direct, substantive
  answer with the actual figures/points — do NOT just say "Filed ✅" or ask
  which company before engaging with the content.
- Do the obvious work without asking permission for each step. Only ask a
  clarifying question when the answer genuinely changes what you'd do AND
  you can't reasonably infer it. Don't ask "should I go through the full
  statement?" — just go through it and report.
- Answer the question that was asked first; offer next steps after.

EXPLICIT INSTRUCTIONS ARE HARD FACTS (read this — past failure here):
- When Liran states an explicit rule about how someone is paid ("Raquel
  Uy gets a fixed $757.50 every two weeks"), treat it as authoritative
  and IMMEDIATELY call set_member_rate with the right unit (e.g.
  half_month). Do NOT default back to 'manual computation needed' on
  a later turn — that's gaslighting him about something he already told you.
- If a rate unit (half_month, day, week, etc.) needs a value he didn't
  give you (e.g. user_id), look it up via list_team_members FIRST,
  then save the rate. Don't ask him for the user_id — it's in the
  Hubstaff roster you already have access to.

SCHEDULING HONESTY (read this — past failures here):
- The remember_fact / commitment kind ONLY stores text in memory. It
  does NOT cause anything to happen later. Storing a 'commitment' fact
  that you'll remind Liran of something does NOTHING by itself.
- For ANY recurring reminder ('every X', 'remind me on the Yth', 'send
  me a payroll summary twice a month'), you MUST call the `set_reminder`
  tool. Saving a fact that talks about the schedule is not enough.
- Never reply 'Saved ✅' or 'Done — reminder set' unless you actually
  called set_reminder and it returned a row id + next_due date.
- If the user describes a schedule, the right pattern is:
    1. Call set_reminder with the appropriate days_of_month + action.
    2. Quote back the returned next_due_date so the user can trust it.
    3. (Optionally) also store a fact for searchable context, but only
       in addition to — never instead of — the actual schedule.

ZOHO SAFETY (read this carefully):
- TWO Zoho organizations: amzg = AMZ-Expert Global Limited (HK, org
  876247837), seo = Pacific Edge Outsourcing LLC (US, org 914942331).
  NEVER confuse them. They are separate legal entities with separate
  accounting, separate tax authorities, and separate customers.
- For ANY Zoho call (read or write): the user must unambiguously name
  the company. If they say "invoice Gilad $3000" without naming the
  entity, REFUSE and ask: "Which company — Pacific Edge (US) or
  AMZ-Expert Global (HK)?" Do NOT guess from context.
- Every Zoho tool reply begins with [ENTITY: <legal name> | Zoho org
  <id>]. Always read the banner. If it doesn't match what you intended,
  STOP and tell the user.
- For WRITES (create_invoice, create_expense, create_customer,
  send_invoice, mark_invoice_paid): the first call returns a confirmation prompt. Show it
  to the user. Only call again with confirmed:true AFTER the user
  explicitly says yes. Never set confirmed:true on your own.

You have tools to recall memory, look up the company structure,
list invoices, and remember facts. Use them.

For "what did we decide" questions, or anything implying a structured
timeline of prior decisions, prefer the recall_decisions tool over
recall — it returns chronological decision-kind facts, not a similarity
search.

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

TELEGRAM FORMATTING — HOW YOUR REPLY GETS RENDERED:
You are writing for Telegram. The server-side formatter converts your
markdown into Telegram HTML before sending. Write structured markdown
deliberately — it will render as a polished, organized reply.

Conversions the formatter applies for you:
- `**bold**` and `# Heading` → real bold text (Telegram HTML <b>).
- Pipe tables → a monospace grey-box block (Telegram <pre>). The
  `|---|---|` separator row is stripped automatically, and columns are
  padded to even width. USE pipe tables for any multi-row metric data
  (open invoices, P&L lines, vendor totals).
- `[Label](url)` → a clickable Telegram link.
- ``` triple-backtick blocks → monospace grey-box (use for raw IDs,
  SQL, code).
- `---` divider lines → stripped (Telegram has no horizontal rule).
- `<`, `>`, `&` in your text are HTML-escaped automatically — write
  them naturally.

What NOT to write:
- `### H3` or `## H2` subheaders — one `# H1` at the top is enough
  if a header helps. Telegram replies should feel like a colleague's
  chat, not a report.
- Long bulleted breakdowns when a pipe table is clearer.
- Decorative dividers like `---`.

Reply shape for a typical data answer:
  # {Topic} — {Scope}
  {One- or two-sentence headline finding with the key number in **bold**.}

  | {Column} | {Column} | {Column} |
  |---|---|---|
  | ... | ... | ... |

  {One short paragraph of "what this means" — actionable, no padding.}

Keep replies short and scannable. A great Telegram reply is a header +
1-2 short paragraphs + (optionally) one pipe table + (optionally) a
question or proposed next action at the end.
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


async def _run_goldman_reply(update, chat_id, llm, user_text, doc_context=None):
    """Run Goldman's agent loop for one user message and send the reply.

    doc_context: optional {"filename", "text"}. When present, the file's
    contents are injected into THIS turn so Goldman answers against the file.
    The conversation history stores only the clean user_text — the file stays
    in memory/Drive and is recallable later — so we don't bloat every turn.
    """
    session_id = _session_id_for_today(chat_id)
    with app_conn() as conn:
        bot_sessions = BotSessionRepository(conn)
        sess = bot_sessions.get_or_create(
            front_door="telegram", chat_id=str(chat_id),
            default_entity="amzg", session_id=session_id,
        )
        entity_slug = sess.current_entity or "amzg"

        turns = ConversationTurnRepository(conn)
        ent = EntityRepository(conn).get_by_slug(entity_slug) if entity_slug else None
        entity_id = ent.id if ent else None

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

        # Inject the attached file's contents into THIS turn only.
        if doc_context and messages and messages[-1]["role"] == "user":
            messages[-1]["content"] = (
                f"[The user attached a file named \"{doc_context['filename']}\". "
                f"Its full contents are between the markers below. Read it and "
                f"answer their message using it — don't just acknowledge it.]\n\n"
                f"<<<FILE>>>\n{doc_context['text']}\n<<<END FILE>>>\n\n"
                f"The user's message: "
                f"{user_text or '(no caption — tell me what this is and what I should do about it.)'}"
            )

        ctx = ToolContext(
            conn=conn, entity_slug=entity_slug,
            chat_id=str(chat_id), embedder=None,
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

    await _reply_html(update.message, reply or "(empty reply)")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not is_allowed_chat(chat_id):
        logger.warning("Denied chat: %s", chat_id)
        return

    user_text = update.message.text or ""
    llm = GoldmanLLM()

    # Cross-message context: if the user just uploaded a file we couldn't
    # auto-file and now names the company (or says "save it"), link this reply
    # to that file and finish the job — instead of treating the two messages
    # as unrelated.
    pending = _PENDING_DOCS.get(chat_id)
    if pending and (time.time() - pending["ts"] < _PENDING_TTL_SECONDS):
        with app_conn() as conn:
            entities = EntityRepository(conn).list_all()
        slug = _entity_from_text(user_text, entities)
        if slug:
            _PENDING_DOCS.pop(chat_id, None)
            await _intake_general_document(
                update=update,
                tmp_path=pending["tmp_path"],
                original_filename=pending["original_filename"],
                entities=entities, llm=llm,
                caption=f"{pending.get('caption', '')} {user_text}".strip(),
                force_entity_slug=slug,
            )
            return
    elif pending:
        # Expired — forget it so we don't file something the user moved on from.
        _PENDING_DOCS.pop(chat_id, None)

    # Recent-attachment context: a file was just uploaded — answer this question
    # against it (once), then let it go so we don't re-inject it every turn.
    doc_context = None
    rec = _RECENT_DOCS.get(chat_id)
    if rec and (time.time() - rec["ts"] < _PENDING_TTL_SECONDS):
        if not rec.get("consumed") and rec.get("text", "").strip():
            doc_context = {"filename": rec["filename"], "text": rec["text"]}
            rec["consumed"] = True
    elif rec:
        _RECENT_DOCS.pop(chat_id, None)

    await _run_goldman_reply(update, chat_id, llm, user_text, doc_context=doc_context)


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

    caption = (msg.caption or "").strip()

    file_obj = await context.bot.get_file(doc.file_id)
    import tempfile
    import os as _os
    # Telegram Photo objects have no file_name. Default suffix per kind:
    # photo → .jpg, document → preserve provided extension (fall back to .pdf
    # only when it's actually a forwarded PDF document).
    is_photo = bool(msg.photo) and not msg.document
    if is_photo:
        suffix = ".jpg"
    else:
        suffix = _os.path.splitext(
            getattr(doc, "file_name", "") or ""
        )[1] or ".pdf"
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
    try:
        parse = parse_bill_file(Path(tmp.name), llm=llm, known_entities=known)
    except Exception as e:
        logger.exception("Bill parser failed on %s: %s", tmp.name, e)
        # Don't leave Liran staring at a silent bot. Route the file to the
        # general-document pipeline so it still lands in memory + Drive.
        await msg.reply_text(
            "Couldn't read that as a bill — it might be a screenshot, "
            "a chart, or a general document. Filing it as a document.",
        )
        await _intake_general_document(
            update=update, tmp_path=tmp.name,
            original_filename=getattr(doc, "file_name", None) or f"telegram-upload{suffix}",
            entities=entities, llm=llm, caption=caption,
        )
        return

    entity_slug = None
    for e in entities:
        if parse.billing_entity and \
           e.legal_name.strip().lower() == parse.billing_entity.strip().lower():
            entity_slug = e.slug
            break

    if not entity_slug:
        # Not a recognisable bill — treat as a general document.
        # Ask Claude to classify which entity it belongs to from the
        # doc content, then ingest + mirror to Drive.
        await _intake_general_document(
            update=update, tmp_path=tmp.name,
            original_filename=getattr(doc, "file_name", None) or f"telegram-upload{suffix}",
            entities=entities, llm=llm, caption=caption,
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
