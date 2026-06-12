"""Phase 11 — real scheduled reminders."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from goldman.reminders.repository import next_due_from
from goldman.reminders.actions import _payroll_period_for_today


# ---- next-due math ----------------------------------------------------------

def test_next_due_picks_next_calendar_day_match():
    # Today is the 10th, configured days are [4, 19].
    assert next_due_from(date(2026, 6, 10), [4, 19]) == date(2026, 6, 19)


def test_next_due_rolls_into_next_month():
    # Today is the 25th, days are [4, 19]. The 19th this month is past;
    # next match is the 4th of next month.
    assert next_due_from(date(2026, 6, 25), [4, 19]) == date(2026, 7, 4)


def test_next_due_handles_end_of_month():
    # Today is the 30th, days are [4]. Next is the 4th of next month.
    assert next_due_from(date(2026, 1, 30), [4]) == date(2026, 2, 4)


def test_next_due_strictly_after_today():
    # If today IS a configured day, the next fire is the NEXT match — not today.
    # (Otherwise we'd re-fire the same reminder immediately after marking it.)
    assert next_due_from(date(2026, 6, 19), [4, 19]) == date(2026, 7, 4)


# ---- payroll period inference ----------------------------------------------

def test_payroll_period_for_19th_covers_first_half_this_month():
    start, stop = _payroll_period_for_today(date(2026, 6, 19))
    assert start == date(2026, 6, 1)
    assert stop == date(2026, 6, 15)


def test_payroll_period_for_4th_covers_last_half_prior_month():
    start, stop = _payroll_period_for_today(date(2026, 7, 4))
    assert start == date(2026, 6, 16)
    assert stop == date(2026, 6, 30)


def test_payroll_period_handles_january_4th_correctly():
    # January 4 should look back at the second half of December.
    start, stop = _payroll_period_for_today(date(2026, 1, 4))
    assert start == date(2025, 12, 16)
    assert stop == date(2025, 12, 31)


# ---- bot tools wiring ------------------------------------------------------

from goldman.bot.tools import TOOL_SCHEMAS, execute_tool


def test_reminder_tools_in_registry():
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert {"set_reminder", "list_reminders", "disable_reminder",
            "fire_reminder_now"}.issubset(names)


def test_set_reminder_rejects_missing_days():
    ctx = MagicMock()
    out = execute_tool(ctx=ctx, name="set_reminder",
                       arguments={"name": "Payroll", "channel_id": "123"})
    assert "days_of_month" in out


def test_set_reminder_persists_and_returns_next_due(monkeypatch):
    fake_row = MagicMock(
        name="r1", days_of_month=[4, 19], action="payroll_reminder",
        channel="telegram", channel_id="7884172049",
        next_due_date=date(2026, 6, 19), id="uuid-1",
    )
    fake_row.name = "Pacific Edge twice-monthly payroll"
    fake_repo = MagicMock()
    fake_repo.upsert_by_name.return_value = fake_row
    with patch("goldman.reminders.repository.ReminderRepository",
                return_value=fake_repo):
        ctx = MagicMock()
        ctx.chat_id = "7884172049"
        out = execute_tool(
            ctx=ctx, name="set_reminder",
            arguments={
                "name": "Pacific Edge twice-monthly payroll",
                "days_of_month": [4, 19],
                "action": "payroll_reminder",
                "channel_id": "7884172049",
            },
        )
    assert "SCHEDULED" in out
    assert "real cron" in out
    assert "2026-06-19" in out
    fake_repo.upsert_by_name.assert_called_once()
