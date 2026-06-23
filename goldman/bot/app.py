"""Goldman Telegram bot Application setup."""

from __future__ import annotations

import asyncio
import logging
import os
import threading

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


async def _on_error(update, context):
    """Global safety net: never let an unhandled exception leave Goldman
    silent. Log the full traceback, then tell the user something went wrong
    so they know to retry instead of staring at a dead chat."""
    logger.exception("Unhandled error while processing update", exc_info=context.error)
    try:
        chat = getattr(update, "effective_chat", None)
        if chat is not None:
            await context.bot.send_message(
                chat_id=chat.id,
                text=(
                    "⚠️ I hit an error handling that and couldn't finish a "
                    "reply. If it was a screenshot or file, try sending the "
                    "text directly — and let Liran know if it keeps happening."
                ),
            )
    except Exception:
        # If even the apology fails, the log above is our record.
        pass


def run_bot():
    """Start the bot (blocking)."""
    token = os.getenv("GOLDMAN_TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("GOLDMAN_TELEGRAM_BOT_TOKEN not set.")

    in_thread = threading.current_thread() is not threading.main_thread()
    if in_thread:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", _start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(_on_error)

    logger.info("Goldman bot starting - long-polling...")
    if in_thread:
        # In a worker thread we can't install signal handlers, so we drive
        # the asyncio lifecycle ourselves instead of using run_polling().
        async def _serve():
            await app.initialize()
            await app.start()
            await app.updater.start_polling(
                allowed_updates=["message", "callback_query"],
            )
            stop_event = asyncio.Event()
            await stop_event.wait()  # block forever
        asyncio.get_event_loop().run_until_complete(_serve())
    else:
        app.run_polling(allowed_updates=["message", "callback_query"])
