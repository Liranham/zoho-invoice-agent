"""Phase 12 — payroll prediction + reconciliation."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from goldman.reminders.actions import (
    ACTIONS, action_payroll_reconciliation,
)


def test_payroll_reconciliation_in_action_registry():
    assert "payroll_reconciliation" in ACTIONS


def test_reconciliation_no_unreconciled_prediction_returns_friendly_note():
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    reminder = MagicMock(name="r")
    reminder.name = "Pacific Edge payroll reconciliation"
    out = action_payroll_reconciliation(conn, reminder, date(2026, 6, 25))
    assert "No unreconciled" in out
    assert "Pacific Edge payroll reconciliation" in out


def test_reconciliation_clean_when_actuals_match_within_tolerance():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    # First fetchone returns the prediction row; second returns the breakdown.
    cur.fetchone.side_effect = [
        ("pred-uuid", date(2026, 6, 1), date(2026, 6, 15),
         "1000.00", "USD"),
        ([{"user_id": 1, "name": "Raquel", "amount": 500},
          {"user_id": 2, "name": "Tirso",  "amount": 500}],),
    ]
    reminder = MagicMock(name="r")
    reminder.name = "Pacific Edge payroll reconciliation"
    with patch("goldman.reminders.actions._hubstaff_actual_payments",
                return_value=[
                    {"user_id": 1, "amount": 500.00, "currency": "USD",
                     "stop_date": "2026-06-15", "payment_source": "payroll",
                     "gateway": "transferwise"},
                    {"user_id": 2, "amount": 500.00, "currency": "USD",
                     "stop_date": "2026-06-15", "payment_source": "payroll",
                     "gateway": "transferwise"},
                ]):
        out = action_payroll_reconciliation(conn, reminder, date(2026, 6, 25))
    assert "clean" in out.lower()
    assert "1,000.00" in out
    assert "Nothing to do" in out


def test_reconciliation_alerts_loudly_on_mismatch_with_per_vaccount_breakdown():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [
        ("pred-uuid", date(2026, 6, 1), date(2026, 6, 15),
         "3000.00", "USD"),
        ([{"user_id": 1, "name": "Raquel", "amount": 1500},
          {"user_id": 2, "name": "Tirso",  "amount": 1500}],),
    ]
    reminder = MagicMock(name="r")
    reminder.name = "Pacific Edge payroll reconciliation"
    with patch("goldman.reminders.actions._hubstaff_actual_payments",
                return_value=[
                    # Only $2,500 went out — Tirso was paid $1,000 instead of $1,500.
                    {"user_id": 1, "amount": 1500.00, "currency": "USD",
                     "stop_date": "2026-06-15"},
                    {"user_id": 2, "amount": 1000.00, "currency": "USD",
                     "stop_date": "2026-06-15"},
                ]):
        out = action_payroll_reconciliation(conn, reminder, date(2026, 6, 25))
    assert "MISMATCH" in out
    assert "3,000.00" in out
    assert "2,500.00" in out
    assert "Tirso" in out
    assert "Raquel" in out
    assert "investigate" in out.lower()


def test_reconciliation_handles_no_hubstaff_payments_recorded():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [
        ("pred-uuid", date(2026, 6, 1), date(2026, 6, 15),
         "1000.00", "USD"),
        ([{"user_id": 1, "name": "Raquel", "amount": 1000}],),
    ]
    reminder = MagicMock(name="r")
    reminder.name = "Pacific Edge payroll reconciliation"
    with patch("goldman.reminders.actions._hubstaff_actual_payments",
                return_value=[]):
        out = action_payroll_reconciliation(conn, reminder, date(2026, 6, 25))
    assert "No completed Hubstaff payments" in out
    assert "MISMATCH" in out


def test_set_reminder_supports_reconciliation_action():
    from goldman.bot.tools import TOOL_SCHEMAS
    set_reminder = next(t for t in TOOL_SCHEMAS if t["name"] == "set_reminder")
    enum = set_reminder["input_schema"]["properties"]["action"]["enum"]
    assert "payroll_reconciliation" in enum
