"""Tests for GoldmanLLM."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from goldman.llm import GoldmanLLM, LLMConfigError


def test_extract_with_tool_returns_tool_input(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")

    fake_response = MagicMock()
    # First block is the tool_use with our extracted data
    block = MagicMock()
    block.type = "tool_use"
    block.name = "submit_extraction"
    block.input = {"tax_registrations": [{"tax_type": "vat"}]}
    fake_response.content = [block]
    fake_response.stop_reason = "tool_use"

    with patch("goldman.llm.anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = fake_response
        mock_anthropic.return_value = mock_client

        llm = GoldmanLLM()
        result = llm.extract_with_tool(
            system="Extract.",
            user_text="VAT registered in UK.",
            tool_name="submit_extraction",
            tool_schema={
                "type": "object",
                "properties": {"tax_registrations": {"type": "array"}},
            },
        )

        assert result == {"tax_registrations": [{"tax_type": "vat"}]}
        # Verify the SDK was called with the right tool
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        assert call_kwargs["tools"][0]["name"] == "submit_extraction"


def test_extract_raises_when_no_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY"):
        GoldmanLLM()


def test_extract_raises_when_response_has_no_tool_use(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")

    fake_response = MagicMock()
    text_block = MagicMock()
    text_block.type = "text"
    fake_response.content = [text_block]
    fake_response.stop_reason = "end_turn"

    with patch("goldman.llm.anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = fake_response
        mock_anthropic.return_value = mock_client

        llm = GoldmanLLM()
        with pytest.raises(RuntimeError, match="did not call the tool"):
            llm.extract_with_tool(
                system="x", user_text="x",
                tool_name="t", tool_schema={"type": "object"},
            )


def test_document_extract_reads_xlsx_cells_not_binary(tmp_path):
    """Regression: an .xlsx must reach Claude as real cell text, not the raw
    binary zip. Previously read_text() on the binary produced gibberish and
    Goldman couldn't tell which company a Wise statement belonged to."""
    from openpyxl import Workbook
    from goldman.llm import _document_extract_with_tool

    wb = Workbook()
    ws = wb.active
    ws.append(["Account holder", "Pacific Edge Outsourcing LLC"])
    ws.append(["Currency", "USD"])
    xlsx = tmp_path / "statement_115834382_USD_2025.xlsx"
    wb.save(xlsx)

    captured = {}

    def _fake_create(**kwargs):
        captured["messages"] = kwargs["messages"]
        block = MagicMock()
        block.type = "tool_use"
        block.name = "classify_document"
        block.input = {"entity_slug": "seo", "category": "Statements"}
        resp = MagicMock()
        resp.content = [block]
        resp.stop_reason = "tool_use"
        return resp

    client = MagicMock()
    client.messages.create.side_effect = _fake_create

    result = _document_extract_with_tool(
        client, "claude-sonnet-4-6", 1024, xlsx,
        "Classify this.", "classify_document",
        {"type": "object", "properties": {"entity_slug": {"type": "string"}}},
    )

    # The content block Claude received must contain the actual cell text.
    sent_text = captured["messages"][0]["content"][0]["text"]
    assert "Pacific Edge Outsourcing LLC" in sent_text
    assert result["entity_slug"] == "seo"
