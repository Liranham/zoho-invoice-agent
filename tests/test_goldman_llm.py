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
