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


def test_ensure_drive_folder_is_in_bot_registry():
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert "ensure_drive_folder" in names


def test_ensure_drive_folder_is_in_mcp_registry():
    names = {t["name"] for t in MCP_TOOLS}
    assert "ensure_drive_folder" in names


def _entity_row(slug="amzg", legal_name="AMZ-Expert Global Limited"):
    # Matches goldman_db.entities._SELECT_COLS column order.
    return (
        "11111111-1111-1111-1111-111111111111", slug, legal_name, "HK",
        None, "USD", "876247837", "AMZG", None, None, None, None,
    )


def test_ensure_drive_folder_creates_missing_segments(monkeypatch):
    monkeypatch.setenv("GOLDMAN_DRIVE_ROOT_FOLDER_ID", "root-x")
    ctx = MagicMock()
    cur = ctx.conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = _entity_row()

    fake_client = MagicMock()
    with patch("goldman.bot.tools._drive_client",
               return_value=(fake_client, "root-x")), \
         patch("goldman.drive.folders.ensure_path", return_value="leaf-id") as ensure_mock:
        out = execute_tool(
            ctx=ctx, name="ensure_drive_folder",
            arguments={"entity": "amzg", "path_segments": ["2026", "July"]},
        )
    ensure_mock.assert_called_once_with(
        fake_client, ["AMZ-Expert Global Limited", "2026", "July"], root_id="root-x",
    )
    assert "leaf-id" in out
    assert "AMZ-Expert Global Limited" in out


def test_ensure_drive_folder_requires_entity_and_segments():
    ctx = MagicMock()
    out = execute_tool(ctx=ctx, name="ensure_drive_folder", arguments={})
    assert "required" in out.lower() or "error" in out.lower()


def _sheet_client(tabs, rows):
    fake = MagicMock()
    fake.get_file_metadata.return_value = {
        "name": "Kizuzim",
        "mimeType": "application/vnd.google-apps.spreadsheet",
    }
    fake.list_sheet_tabs.return_value = tabs
    fake.read_sheet_values.return_value = rows
    return fake


def test_read_drive_file_reads_named_sheet_tab():
    rows = [["Month", "Liran", "Gilad"], ["June26", "1000", "800"]]
    fake = _sheet_client(["May26", "June26"], rows)
    with patch("goldman.bot.tools._drive_client", return_value=(fake, "root")):
        out = execute_tool(ctx=MagicMock(), name="read_drive_file",
                           arguments={"file_id": "sheet1", "tab": "June26"})
    fake.read_sheet_values.assert_called_once_with(file_id="sheet1", tab="June26")
    assert "June26" in out
    assert "1000" in out and "800" in out


def test_read_drive_file_sheet_tab_is_case_insensitive():
    fake = _sheet_client(["June26"], [["x", "1"]])
    with patch("goldman.bot.tools._drive_client", return_value=(fake, "root")):
        out = execute_tool(ctx=MagicMock(), name="read_drive_file",
                           arguments={"file_id": "s", "tab": "june26"})
    # Matched 'June26' despite lowercase request.
    fake.read_sheet_values.assert_called_once_with(file_id="s", tab="June26")
    assert "June26" in out


def test_read_drive_file_unknown_tab_lists_available():
    fake = _sheet_client(["May26", "June26"], [])
    with patch("goldman.bot.tools._drive_client", return_value=(fake, "root")):
        out = execute_tool(ctx=MagicMock(), name="read_drive_file",
                           arguments={"file_id": "s", "tab": "July26"})
    fake.read_sheet_values.assert_not_called()
    assert "May26" in out and "June26" in out


def test_read_drive_file_no_tab_lists_tabs_and_reads_first():
    fake = _sheet_client(["May26", "June26"], [["header"]])
    with patch("goldman.bot.tools._drive_client", return_value=(fake, "root")):
        out = execute_tool(ctx=MagicMock(), name="read_drive_file",
                           arguments={"file_id": "s"})
    fake.read_sheet_values.assert_called_once_with(file_id="s", tab="May26")
    assert "May26" in out and "June26" in out


def test_read_drive_file_exports_google_doc_text():
    fake = MagicMock()
    fake.get_file_metadata.return_value = {
        "name": "Meeting Notes",
        "mimeType": "application/vnd.google-apps.document",
    }
    fake.export_text.return_value = "Discussed the June offsets."
    with patch("goldman.bot.tools._drive_client", return_value=(fake, "root")):
        out = execute_tool(ctx=MagicMock(), name="read_drive_file",
                           arguments={"file_id": "doc1"})
    fake.export_text.assert_called_once_with(file_id="doc1", mime="text/plain")
    assert "Discussed the June offsets." in out
