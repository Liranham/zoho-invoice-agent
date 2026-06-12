"""Action handlers for scheduled reminders.

Each handler receives (conn, reminder, today) and returns a Markdown-ish
text message. The tick layer takes care of channel delivery (Telegram /
HTTP API / etc.) and audit logging.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from calendar import monthrange


# ---- payroll_reminder -----------------------------------------------------

def _payroll_period_for_today(today: date) -> tuple:
    """Given today (a reminder firing date), figure out which Pacific Edge
    Hubstaff period the user needs to pay for.

    Liran's rule (from the conversation he had with Goldman):
      * Hubstaff cuts at the 15th and end-of-month.
      * He reminds on the 4th (covers prior month's 16th → end)
        and the 19th (covers this month's 1st → 15th).

    The exact firing date can shift (e.g. fired late, fired manually);
    just pick the most-recent CLOSED period whose stop date is the
    closest <= today.
    """
    # Candidate periods near today: previous-month half-2, this-month half-1
    # and this-month half-2 (in case the reminder is late).
    candidates = []
    # this month, half-1: 1..15
    candidates.append((date(today.year, today.month, 1),
                       date(today.year, today.month, 15)))
    # this month, half-2: 16..end_of_month
    last_day_this = monthrange(today.year, today.month)[1]
    candidates.append((date(today.year, today.month, 16),
                       date(today.year, today.month, last_day_this)))
    # previous month, half-2: 16..end_of_month
    prev = (today.replace(day=1) - timedelta(days=1))
    last_day_prev = monthrange(prev.year, prev.month)[1]
    candidates.append((date(prev.year, prev.month, 16),
                       date(prev.year, prev.month, last_day_prev)))
    # previous month, half-1: 1..15
    candidates.append((date(prev.year, prev.month, 1),
                       date(prev.year, prev.month, 15)))
    # Pick the most-recent period whose stop is strictly before today.
    closed = [(s, e) for (s, e) in candidates if e < today]
    if not closed:
        return candidates[0]
    return max(closed, key=lambda se: se[1])


def _payroll_summary_text(conn, start: date, stop: date) -> str:
    """Reuse the bot tool's payroll_summary handler but bypass ctx
    (we don't have a ToolContext at scheduler time)."""
    from goldman.bot.tools import _hubstaff_payroll_summary
    from unittest.mock import MagicMock
    ctx = MagicMock()
    ctx.conn = conn
    ctx.chat_id = "scheduler-tick"
    return _hubstaff_payroll_summary(ctx, {
        "start": start.isoformat(),
        "stop": stop.isoformat(),
    })


def action_payroll_reminder(conn, reminder, today: date) -> str:
    """Produce the payroll-due message for today's firing."""
    start, stop = _payroll_period_for_today(today)
    body = _payroll_summary_text(conn, start, stop)
    return (
        f"🗓️  *Payroll reminder — {reminder.name}*\n"
        f"It's {today.strftime('%a %b %-d')}. Time to send Wise payments "
        f"for the **{start.isoformat()} → {stop.isoformat()}** period.\n\n"
        f"{body}"
    )


# ---- generic_note_reminder -----------------------------------------------

def action_generic_note(conn, reminder, today: date) -> str:
    """Just remind Liran of the configured text."""
    note = (reminder.action_params or {}).get("note") or reminder.name
    return f"🔔 *Reminder — {reminder.name}*\n{note}"


ACTIONS = {
    "payroll_reminder": action_payroll_reminder,
    "generic_note":     action_generic_note,
}


def run_action(conn, reminder, today: date) -> str:
    handler = ACTIONS.get(reminder.action)
    if not handler:
        return f"⚠️ Unknown reminder action {reminder.action!r}."
    return handler(conn, reminder, today)
