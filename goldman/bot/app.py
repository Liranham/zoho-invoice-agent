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
