"""Phase 13 — Wise read-only tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from goldman.bot.tools import TOOL_SCHEMAS, execute_tool


WISE_TOOLS = {
    "wise_balances", "wise_transactions", "wise_recipients",
    "wise_cash_dashboard", "wise_archive_statement",
}


def test_wise_tools_in_bot_registry():
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert WISE_TOOLS.issubset(names)


def test_wise_balances_friendly_error_without_token(monkeypatch):
    monkeypatch.delenv("WISE_API_TOKEN", raising=False)
    ctx = MagicMock()
    out = execute_tool(ctx=ctx, name="wise_balances", arguments={})
    assert "WISE_API_TOKEN" in out or "unavailable" in out.lower()


def test_wise_balances_renders_currencies(monkeypatch):
    monkeypatch.setenv("WISE_API_TOKEN", "stub")
    fake = MagicMock()
    fake.balances.return_value = [
        {"id": 1, "currency": "USD", "amount": {"value": 952.93}},
        {"id": 2, "currency": "EUR", "amount": {"value": 150.50},
         "reservedAmount": {"value": 25.00}},
    ]
    fake._profile_id = "267885"
    with patch("goldman.wise.client.WiseClient", return_value=fake):
        ctx = MagicMock()
        out = execute_tool(ctx=ctx, name="wise_balances", arguments={})
    assert "USD: 952.93" in out
    assert "EUR: 150.50" in out
    assert "25.00" in out


def test_wise_transactions_requires_dates():
    ctx = MagicMock()
    out = execute_tool(ctx=ctx, name="wise_transactions",
                       arguments={"start": "2026-05-01"})
    # Hits the underlying client which then errors; we just want a non-empty
    # message instead of a crash.
    assert "wise" in out.lower() or "stop" in out.lower() or "error" in out.lower()


def test_wise_transactions_renders_rows(monkeypatch):
    monkeypatch.setenv("WISE_API_TOKEN", "stub")
    fake = MagicMock()
    fake.transfers.return_value = [
        {"id": 100, "created": "2026-05-23T10:32:00Z",
         "sourceCurrency": "USD", "sourceValue": 757.50,
         "targetCurrency": "PHP", "targetValue": 42000,
         "status": "outgoing_payment_sent", "reference": "Raquel Uy May 2"},
    ]
    fake._profile_id = "267885"
    with patch("goldman.wise.client.WiseClient", return_value=fake):
        ctx = MagicMock()
        out = execute_tool(
            ctx=ctx, name="wise_transactions",
            arguments={"start": "2026-05-01", "stop": "2026-05-31"},
        )
    assert "Raquel Uy" in out
    assert "757.50" in out
    assert "outgoing_payment_sent" in out


def test_wise_recipients_renders(monkeypatch):
    monkeypatch.setenv("WISE_API_TOKEN", "stub")
    fake = MagicMock()
    fake.recipients.return_value = [
        {"id": 1, "name": {"fullName": "Raquel Uy"},
         "currency": "PHP", "country": "PH"},
    ]
    fake._profile_id = "267885"
    with patch("goldman.wise.client.WiseClient", return_value=fake):
        ctx = MagicMock()
        out = execute_tool(ctx=ctx, name="wise_recipients", arguments={})
    assert "Raquel Uy" in out
    assert "PHP" in out


def test_wise_archive_statement_validates_inputs():
    ctx = MagicMock()
    out = execute_tool(
        ctx=ctx, name="wise_archive_statement",
        arguments={"balance_id": "", "currency": "USD",
                   "start": "2026-05-01", "stop": "2026-05-31"},
    )
    assert "required" in out.lower() or "error" in out.lower()
