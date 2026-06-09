"""Tests for the MCP server endpoint."""

from __future__ import annotations

import json
from unittest.mock import patch

from goldman.api.mcp_server import handle_mcp, TOOLS


def _headers(key: str = "test-key") -> dict:
    return {"Authorization": f"Bearer {key}"}


def test_handle_mcp_rejects_missing_auth(monkeypatch):
    monkeypatch.setenv("GOLDMAN_API_KEY", "test-key")
    code, _ = handle_mcp(headers={}, raw_body=b'{"jsonrpc":"2.0","id":1,"method":"ping"}')
    assert code == 401


def test_handle_mcp_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("GOLDMAN_API_KEY", "right-key")
    code, _ = handle_mcp(
        headers={"Authorization": "Bearer wrong-key"},
        raw_body=b'{"jsonrpc":"2.0","id":1,"method":"ping"}',
    )
    assert code == 401


def test_initialize_returns_protocol_version_and_capabilities(monkeypatch):
    monkeypatch.setenv("GOLDMAN_API_KEY", "test-key")
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18",
                   "capabilities": {}, "clientInfo": {"name": "claude-ai"}},
    }).encode()
    code, payload = handle_mcp(headers=_headers(), raw_body=body)
    assert code == 200
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == 1
    assert payload["result"]["serverInfo"]["name"] == "goldman"
    assert "tools" in payload["result"]["capabilities"]


def test_tools_list_returns_goldman_tools(monkeypatch):
    monkeypatch.setenv("GOLDMAN_API_KEY", "test-key")
    body = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()
    code, payload = handle_mcp(headers=_headers(), raw_body=body)
    assert code == 200
    names = {t["name"] for t in payload["result"]["tools"]}
    assert "ask_goldman" in names
    assert "who" in names
    assert "recall" in names
    assert "decisions" in names
    assert "remember" in names


def test_tools_call_routes_to_ask_goldman(monkeypatch):
    monkeypatch.setenv("GOLDMAN_API_KEY", "test-key")
    with patch("goldman.ask.ask_goldman") as mock_ask:
        mock_ask.return_value = {
            "answer": "Two entities: AMZG and Pacific Edge.",
            "entity": "amzg", "session_id": "s",
        }
        body = json.dumps({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "ask_goldman",
                       "arguments": {"question": "what entities?"}},
        }).encode()
        code, payload = handle_mcp(headers=_headers(), raw_body=body)
    assert code == 200
    assert payload["result"]["isError"] is False
    assert "Two entities" in payload["result"]["content"][0]["text"]


def test_tools_call_unknown_tool_returns_isError(monkeypatch):
    monkeypatch.setenv("GOLDMAN_API_KEY", "test-key")
    body = json.dumps({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "not_a_tool", "arguments": {}},
    }).encode()
    code, payload = handle_mcp(headers=_headers(), raw_body=body)
    assert code == 200
    assert payload["result"]["isError"] is True


def test_notifications_initialized_returns_202_no_body(monkeypatch):
    monkeypatch.setenv("GOLDMAN_API_KEY", "test-key")
    body = json.dumps({
        "jsonrpc": "2.0", "method": "notifications/initialized",
    }).encode()
    code, payload = handle_mcp(headers=_headers(), raw_body=body)
    assert code == 202
    assert payload is None


def test_unknown_method_returns_jsonrpc_error(monkeypatch):
    monkeypatch.setenv("GOLDMAN_API_KEY", "test-key")
    body = json.dumps({"jsonrpc": "2.0", "id": 5, "method": "bogus"}).encode()
    code, payload = handle_mcp(headers=_headers(), raw_body=body)
    assert code == 200
    assert payload["error"]["code"] == -32601
