"""Tests for the stdlib HTTPS fallback client for Goldman's MCP endpoint."""

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

import goldman_mcp
from goldman_mcp import GoldmanMCPError, call_tool, list_tools, load_api_key


def _response(payload):
    """Build a context-manager stand-in for urlopen's return value."""
    handle = MagicMock()
    handle.read.return_value = json.dumps(payload).encode("utf-8")
    ctx = MagicMock()
    ctx.__enter__.return_value = handle
    return ctx


def _text_result(text):
    return {"result": {"content": [{"type": "text", "text": text}]}}


@patch("goldman_mcp.urllib.request.urlopen")
def test_call_tool_returns_text_and_sends_bearer_auth(mock_urlopen):
    mock_urlopen.return_value = _response(_text_result("Created invoice INV-23"))

    out = call_tool("create_invoice", {"entity": "seo"}, api_key="k_test")

    assert out == "Created invoice INV-23"
    request = mock_urlopen.call_args[0][0]
    assert request.full_url == goldman_mcp.DEFAULT_ENDPOINT
    assert request.headers["Authorization"] == "Bearer k_test"
    body = json.loads(request.data.decode("utf-8"))
    assert body["method"] == "tools/call"
    assert body["params"] == {"name": "create_invoice", "arguments": {"entity": "seo"}}


@patch("goldman_mcp.urllib.request.urlopen")
def test_call_tool_joins_multiple_content_blocks(mock_urlopen):
    mock_urlopen.return_value = _response(
        {"result": {"content": [{"text": "part one "}, {"text": "part two"}]}}
    )

    assert call_tool("ask_goldman", api_key="k") == "part one part two"


@patch("goldman_mcp.urllib.request.urlopen")
def test_list_tools_returns_names(mock_urlopen):
    mock_urlopen.return_value = _response(
        {"result": {"tools": [{"name": "create_invoice"}, {"name": "notify_liran"}]}}
    )

    assert list_tools(api_key="k") == ["create_invoice", "notify_liran"]


@patch("goldman_mcp.urllib.request.urlopen")
def test_jsonrpc_error_raises_rather_than_returning_empty(mock_urlopen):
    """A silent empty string here would look identical to 'no new payment'."""
    mock_urlopen.return_value = _response({"error": {"code": -32603, "message": "boom"}})

    with pytest.raises(GoldmanMCPError, match="boom"):
        call_tool("wise_transactions", api_key="k")


@patch("goldman_mcp.urllib.request.urlopen")
def test_http_error_surfaces_status_and_body(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.HTTPError(
        goldman_mcp.DEFAULT_ENDPOINT, 401, "Unauthorized", {}, io.BytesIO(b"bad key")
    )

    with pytest.raises(GoldmanMCPError, match="HTTP 401"):
        call_tool("wise_transactions", api_key="k")


@patch("goldman_mcp.urllib.request.urlopen")
def test_unreachable_endpoint_raises(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.URLError("connection refused")

    with pytest.raises(GoldmanMCPError, match="Could not reach Goldman"):
        call_tool("wise_transactions", api_key="k")


@patch("goldman_mcp.urllib.request.urlopen")
def test_non_json_response_raises(mock_urlopen):
    handle = MagicMock()
    handle.read.return_value = b"<html>502 Bad Gateway</html>"
    ctx = MagicMock()
    ctx.__enter__.return_value = handle
    mock_urlopen.return_value = ctx

    with pytest.raises(GoldmanMCPError, match="non-JSON"):
        call_tool("wise_transactions", api_key="k")


def test_load_api_key_prefers_environment(monkeypatch):
    monkeypatch.setenv("GOLDMAN_API_KEY", "from_env")
    assert load_api_key() == "from_env"


def test_load_api_key_falls_back_to_env_file(monkeypatch, tmp_path):
    monkeypatch.delenv("GOLDMAN_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text('OTHER=1\nGOLDMAN_API_KEY="from_file"\n')

    assert load_api_key(env_path=str(env_file)) == "from_file"


def test_load_api_key_raises_when_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("GOLDMAN_API_KEY", raising=False)

    with pytest.raises(GoldmanMCPError, match="not found"):
        load_api_key(env_path=str(tmp_path / "absent.env"))
