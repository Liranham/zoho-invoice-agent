"""Goldman Telegram bot Application setup."""

from __future__ import annotations

import logging
import os

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

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", _start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Goldman bot starting - long-polling...")
    app.run_polling(allowed_updates=["message", "callback_query"])
