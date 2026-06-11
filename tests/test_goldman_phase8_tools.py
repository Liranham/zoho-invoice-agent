"""Phase 8 — verify the new agent tools are wired through the dispatcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from goldman.bot.tools import TOOL_SCHEMAS, execute_tool
from goldman.api.mcp_server import TOOLS as MCP_TOOLS


PHASE_8_TOOLS = {
    "search_emails", "read_email_thread", "draft_email",
    "list_drive_folder", "read_drive_file",
    "create_invoice", "list_customers", "create_customer",
    "create_expense", "send_invoice",
}


def test_phase_8_tools_are_in_bot_registry():
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert PHASE_8_TOOLS.issubset(names), \
        f"Missing from bot registry: {PHASE_8_TOOLS - names}"


def test_phase_8_tools_are_in_mcp_registry():
    names = {t["name"] for t in MCP_TOOLS}
    assert PHASE_8_TOOLS.issubset(names), \
        f"Missing from MCP registry: {PHASE_8_TOOLS - names}"


def test_search_emails_empty_query_returns_error_text():
    ctx = MagicMock()
    result = execute_tool(ctx=ctx, name="search_emails", arguments={"query": "   "})
    assert "empty query" in result.lower() or "error" in result.lower()


def test_draft_email_validates_required_fields():
    ctx = MagicMock()
    result = execute_tool(ctx=ctx, name="draft_email", arguments={})
    assert "required" in result.lower() or "error" in result.lower()


def test_create_invoice_validates_entity():
    ctx = MagicMock()
    # No such entity → guardrail (Phase 9) refuses, listing both options.
    cur = ctx.conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = None
    result = execute_tool(
        ctx=ctx, name="create_invoice",
        arguments={"entity": "bogus", "customer_id": "x", "amount": 1},
    )
    assert "amz-expert global" in result.lower()
    assert "pacific edge" in result.lower()


def test_list_customers_validates_entity():
    ctx = MagicMock()
    cur = ctx.conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = None
    result = execute_tool(
        ctx=ctx, name="list_customers", arguments={"entity": "wrong"},
    )
    assert "amz-expert global" in result.lower()
    assert "pacific edge" in result.lower()


def test_search_emails_uses_gmail_client(monkeypatch):
    monkeypatch.setenv("GMAIL_CREDENTIALS_B64", "stub")
    monkeypatch.setenv("GMAIL_TOKEN_B64", "stub")
    fake = MagicMock()
    fake.search.return_value = [{
        "message_id": "m1", "thread_id": "t1",
        "subject": "Invoice 22", "from": "vendor@x.com",
        "to": "me@x.com", "date": "Mon, 10 Jun 2026 09:00",
        "snippet": "Please pay invoice 22",
    }]
    with patch("goldman.bot.tools._gmail_client", return_value=fake):
        ctx = MagicMock()
        out = execute_tool(
            ctx=ctx, name="search_emails",
            arguments={"query": "subject:invoice", "limit": 5},
        )
    assert "Invoice 22" in out
    assert "t1" in out
    fake.search.assert_called_once()


def test_list_drive_folder_uses_drive_client(monkeypatch):
    monkeypatch.setenv("GOLDMAN_DRIVE_ROOT_FOLDER_ID", "root-x")
    fake_client = MagicMock()
    fake_client.list_children.return_value = [
        {"id": "f1", "name": "Pacific Edge",
         "mimeType": "application/vnd.google-apps.folder"},
        {"id": "d1", "name": "BR.pdf",
         "mimeType": "application/pdf", "size": "12345"},
    ]
    with patch("goldman.bot.tools._drive_client",
               return_value=(fake_client, "root-x")):
        ctx = MagicMock()
        out = execute_tool(ctx=ctx, name="list_drive_folder", arguments={})
    assert "Pacific Edge" in out
    assert "BR.pdf" in out
