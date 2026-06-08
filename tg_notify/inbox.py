"""
Process inbound Telegram updates (button presses on unknown-sender prompts).

We use webhook delivery — Telegram POSTs to /webhook/telegram on the Render
service. This module exposes `process_update(update_dict, automation)`, which
the HTTP handler calls for each incoming update.

Callback data format produced by wise/handler.py:
    "wise:skip:{dedup_key}"
    "wise:map:{CLIENT_KEY}:{dedup_key}"
where CLIENT_KEY is a key in wise.handler.CLIENT_MAPPING.

For map-actions, we read the stashed payload from
state/pending/<dedup_key>.json, set the resolved customer, and re-run the
invoice creation (skipping the unknown-sender check).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from wise.handler import CLIENT_MAPPING, WiseAutomation

logger = logging.getLogger(__name__)


def process_update(update: dict, automation: WiseAutomation, notifier=None) -> None:
    """Handle a single Telegram update."""
    callback = update.get("callback_query")
    if not callback:
        # Ignore non-button messages for now.
        return

    callback_id = callback.get("id")
    data = callback.get("data") or ""
    message = callback.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")

    parts = data.split(":", 3)
    if len(parts) < 2 or parts[0] != "wise":
        if notifier and callback_id:
            notifier.answer_callback_query(callback_id, "unknown action")
        return

    action = parts[1]
    if action == "skip" and len(parts) >= 3:
        dedup_key = parts[2]
        _resolve_pending(automation, dedup_key, mapped_client_key=None)
        if notifier:
            notifier.answer_callback_query(callback_id, "skipped")
            if chat_id and message_id:
                notifier.edit_message_text(chat_id, message_id, "✋ Skipped — no invoice created.")
        return

    if action == "map" and len(parts) >= 4:
        client_key = parts[2]
        dedup_key = parts[3]
        if client_key not in CLIENT_MAPPING:
            if notifier:
                notifier.answer_callback_query(callback_id, f"unknown client {client_key}")
            return
        ok = _resolve_pending(automation, dedup_key, mapped_client_key=client_key)
        if notifier:
            notifier.answer_callback_query(callback_id, "creating…" if ok else "error")
            if chat_id and message_id:
                msg = f"➡️ Mapped to {client_key}, processing…" if ok else "❌ Failed to resolve."
                notifier.edit_message_text(chat_id, message_id, msg)
        return


def _resolve_pending(
    automation: WiseAutomation,
    dedup_key: str,
    mapped_client_key: str | None,
) -> bool:
    """Load the stashed payload and resume processing under the chosen client.

    For 'skip', we just mark the dedup_key processed so we never see it again.
    For 'map', we forge a sender_name override and re-enter _create_invoice.
    """
    pending_dir = automation.state_path.parent / "pending"
    pending_file = pending_dir / f"{dedup_key.replace(':', '_')}.json"

    if mapped_client_key is None:
        # Skip: just mark processed, drop the pending file
        automation._mark_processed(dedup_key)
        try:
            pending_file.unlink(missing_ok=True)
        except OSError:
            pass
        return True

    try:
        payload = json.loads(pending_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error("Pending payload missing for %s: %s", dedup_key, e)
        return False

    # Re-enter _create_invoice with the chosen sender_name. We need amount,
    # currency, occurred_at — which we re-extract using the same logic.
    data = payload.get("data") or {}
    resource = data.get("resource") or {}
    amount = WiseAutomation._extract_amount(data)
    currency = data.get("currency") or resource.get("currency") or "USD"
    occurred_at = data.get("occurred_at") or payload.get("sent_at") or ""

    try:
        ok = automation._create_invoice(
            sender_name=mapped_client_key,
            amount=amount or 0.0,
            currency=currency,
            occurred_at=occurred_at,
            dedup_key=dedup_key,
            payload=payload,
        )
    except Exception as e:
        logger.exception("Resolve failed for %s: %s", dedup_key, e)
        return False

    if ok:
        try:
            pending_file.unlink(missing_ok=True)
        except OSError:
            pass
    return ok
