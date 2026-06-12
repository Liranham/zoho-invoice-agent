"""Phase 10 — Hubstaff tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from goldman.bot.tools import TOOL_SCHEMAS, execute_tool


HUBSTAFF_TOOLS = {
    "list_team_members", "hours_worked", "set_member_rate",
    "payroll_summary", "payroll_anomalies",
}


def test_hubstaff_tools_are_in_bot_registry():
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert HUBSTAFF_TOOLS.issubset(names)


def test_hours_worked_requires_dates():
    ctx = MagicMock()
    ctx.conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("seo-id",)
    out = execute_tool(ctx=ctx, name="hours_worked", arguments={"start": "2026-06-01"})
    assert "required" in out.lower() or "error" in out.lower()


def test_list_team_members_no_pat_returns_friendly_error(monkeypatch):
    # Phase 11 persistence: also stub the DB-cached PAT lookup to return None,
    # otherwise the client picks up a real persisted PAT from the live DB.
    monkeypatch.delenv("HUBSTAFF_PAT", raising=False)
    with patch("goldman.hubstaff.client._load_persisted_pat", return_value=None):
        ctx = MagicMock()
        ctx.conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("seo-id",)
        out = execute_tool(ctx=ctx, name="list_team_members", arguments={})
    assert "HUBSTAFF_PAT" in out or "unavailable" in out.lower()


def test_hours_worked_uses_hubstaff_client(monkeypatch):
    monkeypatch.setenv("HUBSTAFF_PAT", "stub")
    ctx = MagicMock()
    ctx.conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("seo-id",)
    fake = MagicMock()
    fake.org_id = "267885"
    fake.daily_activities.return_value = [
        {"user_id": 890043, "tracked": 36000, "billable": 32400, "date": "2026-06-09"},
        {"user_id": 890043, "tracked": 14400, "billable": 14400, "date": "2026-06-10"},
        {"user_id": 1533905, "tracked": 7200, "billable": 7200, "date": "2026-06-09"},
    ]
    fake.members.return_value = ([], {890043: {"id": 890043, "name": "Raquel Uy"},
                                       1533905: {"id": 1533905, "name": "Terxie Albesa"}})
    with patch("goldman.hubstaff.client.HubstaffClient", return_value=fake):
        out = execute_tool(
            ctx=ctx, name="hours_worked",
            arguments={"start": "2026-06-09", "stop": "2026-06-12"},
        )
    assert "Raquel Uy" in out
    assert "Terxie Albesa" in out
    assert "14.00h" in out  # 50400 seconds / 3600 = 14.00
    assert "Pacific Edge" in out
    assert "267885" in out


def test_payroll_summary_flags_missing_rates(monkeypatch):
    monkeypatch.setenv("HUBSTAFF_PAT", "stub")
    ctx = MagicMock()
    ctx.conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("seo-id",)
    fake = MagicMock()
    fake.org_id = "267885"
    fake.daily_activities.return_value = [
        {"user_id": 890043, "tracked": 36000, "billable": 36000, "date": "2026-06-09"},
    ]
    fake.members.return_value = ([], {890043: {"id": 890043, "name": "Raquel Uy"}})
    with patch("goldman.hubstaff.client.HubstaffClient", return_value=fake), \
         patch("goldman.hubstaff.rates.MemberRateRepository") as mock_rates:
        mock_rates.return_value.list_for_entity.return_value = []
        out = execute_tool(
            ctx=ctx, name="payroll_summary",
            arguments={"start": "2026-06-09", "stop": "2026-06-09"},
        )
    assert "no rate on file" in out.lower()
    assert "Raquel Uy" in out
    assert "set_member_rate" in out.lower()


def test_payroll_summary_computes_total_with_rate(monkeypatch):
    monkeypatch.setenv("HUBSTAFF_PAT", "stub")
    from decimal import Decimal
    from goldman.hubstaff.rates import MemberRate
    ctx = MagicMock()
    ctx.conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("seo-id",)
    fake = MagicMock()
    fake.org_id = "267885"
    # Raquel did 10 hours.
    fake.daily_activities.return_value = [
        {"user_id": 890043, "tracked": 36000, "billable": 36000, "date": "2026-06-09"},
    ]
    fake.members.return_value = ([], {890043: {"id": 890043, "name": "Raquel Uy"}})
    rate = MemberRate(
        hubstaff_user_id=890043, full_name="Raquel Uy",
        rate_amount=Decimal("7.50"), rate_currency="USD", rate_unit="hour",
    )
    with patch("goldman.hubstaff.client.HubstaffClient", return_value=fake), \
         patch("goldman.hubstaff.rates.MemberRateRepository") as mock_rates:
        mock_rates.return_value.list_for_entity.return_value = [rate]
        out = execute_tool(
            ctx=ctx, name="payroll_summary",
            arguments={"start": "2026-06-09", "stop": "2026-06-09"},
        )
    assert "75.00" in out  # 10h × $7.50
    assert "GRAND TOTAL" in out
