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
    token = os.getenv("GOLDMAN_TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.warning("No GOLDMAN_TELEGRAM_BOT_TOKEN — can't deliver reminder.")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text,
                   "parse_mode": "Markdown",
                   "disable_web_page_preview": True},
            timeout=20,
        )
        ok = resp.status_code == 200 and resp.json().get("ok") is True
        if not ok:
            logger.warning("Telegram sendMessage failed: %s %s",
                           resp.status_code, resp.text[:200])
        return ok
    except Exception as e:
        logger.exception("Telegram delivery error: %s", e)
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
