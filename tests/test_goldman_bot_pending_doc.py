"""A held-but-unfiled upload must never be denied.

2026-07-21: Liran sent an invoice PDF, then a separate text message about it.
Goldman answered the PDF with "Got Invoice-BBDEC7B1-0053.pdf — which company?"
and, eight seconds later, answered the text with "I don't see any file or image
attached to your message." Both were true from each handler's point of view and
the pair was nonsense to read.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from goldman.bot import handlers
from goldman.bot.handlers import pending_doc_prompt


def test_pending_doc_prompt_asserts_the_file_exists():
    prompt = pending_doc_prompt("Invoice-BBDEC7B1-0053.pdf", "please take care of it")

    assert "Invoice-BBDEC7B1-0053.pdf" in prompt
    assert "please take care of it" in prompt
    # The whole point: forbid the denial and demand the company question.
    assert "no file was attached" in prompt
    assert "which one it is" in prompt


def _update(chat_id: int, text: str):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message.text = text
    return update


def test_unmatched_text_keeps_pending_doc_and_flags_it_to_the_agent():
    chat_id = 7884172049
    handlers._PENDING_DOCS[chat_id] = {
        "tmp_path": "/tmp/invoice.pdf",
        "original_filename": "Invoice-BBDEC7B1-0053.pdf",
        "caption": "",
        "ts": time.time(),
    }

    reply = AsyncMock()
    try:
        with patch.object(handlers, "is_allowed_chat", return_value=True), \
             patch.object(handlers, "GoldmanLLM"), \
             patch.object(handlers, "app_conn"), \
             patch.object(handlers, "EntityRepository"), \
             patch.object(handlers, "_entity_from_text", return_value=None), \
             patch.object(handlers, "_run_goldman_reply", reply):
            asyncio.run(handlers.handle_text(
                _update(chat_id, "Here is an invoice please take care of it"), MagicMock()
            ))

        assert reply.await_args.kwargs["pending_filename"] == "Invoice-BBDEC7B1-0053.pdf"
        # The file is still held, so naming the company next turn still files it.
        assert chat_id in handlers._PENDING_DOCS
    finally:
        handlers._PENDING_DOCS.pop(chat_id, None)


def test_text_naming_the_company_files_the_doc_and_does_not_flag_it():
    chat_id = 7884172049
    handlers._PENDING_DOCS[chat_id] = {
        "tmp_path": "/tmp/invoice.pdf",
        "original_filename": "Invoice-BBDEC7B1-0053.pdf",
        "caption": "",
        "ts": time.time(),
    }

    intake = AsyncMock()
    reply = AsyncMock()
    try:
        with patch.object(handlers, "is_allowed_chat", return_value=True), \
             patch.object(handlers, "GoldmanLLM"), \
             patch.object(handlers, "app_conn"), \
             patch.object(handlers, "EntityRepository"), \
             patch.object(handlers, "_entity_from_text", return_value="amzg"), \
             patch.object(handlers, "_intake_general_document", intake), \
             patch.object(handlers, "_run_goldman_reply", reply):
            asyncio.run(handlers.handle_text(_update(chat_id, "Amz-expert"), MagicMock()))

        assert intake.await_args.kwargs["force_entity_slug"] == "amzg"
        reply.assert_not_awaited()
        assert chat_id not in handlers._PENDING_DOCS
    finally:
        handlers._PENDING_DOCS.pop(chat_id, None)
