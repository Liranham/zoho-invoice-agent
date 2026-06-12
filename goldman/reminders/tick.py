"""Daily scheduler tick: find due reminders and deliver them."""

from __future__ import annotations

import logging
import os
from datetime import date

import requests

from goldman.reminders.actions import run_action
from goldman.reminders.repository import (
    ReminderRepository, next_due_from,
)
from goldman_db.connection import app_conn

logger = logging.getLogger(__name__)


def _deliver_telegram(chat_id: str, text: str) -> bool:
    """Send to Telegram. Try Markdown first; if Telegram rejects on
    parse error (stray `_` / `*` in a contractor's name etc.), retry as
    plain text so the message still lands."""
    token = os.getenv("GOLDMAN_TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.warning("No GOLDMAN_TELEGRAM_BOT_TOKEN — can't deliver reminder.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    base = {"chat_id": chat_id, "text": text,
            "disable_web_page_preview": True}
    for attempt in ("Markdown", None):
        body = dict(base)
        if attempt:
            body["parse_mode"] = attempt
        try:
            resp = requests.post(url, json=body, timeout=20)
            if resp.status_code == 200 and resp.json().get("ok") is True:
                if not attempt:
                    logger.info("Telegram delivered as plain text (Markdown was rejected).")
                return True
            logger.warning("Telegram sendMessage failed (parse_mode=%s): %s %s",
                           attempt, resp.status_code, resp.text[:200])
        except Exception as e:
            logger.exception("Telegram delivery error (parse_mode=%s): %s",
                              attempt, e)
    return False


def run_reminder_tick(today=None) -> int:
    """Look for due reminders and fire them. Returns number fired."""
    today = today or date.today()
    fired = 0
    with app_conn() as conn:
        repo = ReminderRepository(conn)
        due = repo.list_due(today)
        if not due:
            logger.info("Reminder tick: nothing due on %s.", today.isoformat())
            return 0
        logger.info("Reminder tick: %d due on %s.", len(due), today.isoformat())
        for r in due:
            try:
                text = run_action(conn, r, today)
                delivered = False
                if r.channel == "telegram":
                    delivered = _deliver_telegram(r.channel_id, text)
                else:
                    logger.warning("Unknown channel %r for reminder %s",
                                   r.channel, r.id)
                next_due = next_due_from(today, r.days_of_month)
                summary = ("delivered" if delivered else "DELIVERY FAILED") \
                          + f" — {len(text)} chars"
                repo.mark_fired(
                    r.id, next_due_date=next_due, result_summary=summary,
                )
                if delivered:
                    fired += 1
            except Exception as e:
                logger.exception("Reminder %s failed: %s", r.id, e)
        conn.commit()
    return fired
