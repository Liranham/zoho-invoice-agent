"""Tests for the agent loop."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from goldman.bot.agent import run_agent


def test_agent_returns_text_when_no_tool_use():
    fake_claude = MagicMock()
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Hello from Goldman."
    resp = MagicMock()
    resp.content = [text_block]
    resp.stop_reason = "end_turn"
    fake_claude.messages.create.return_value = resp

    ctx = MagicMock()
    result = run_agent(
        claude=fake_claude, model="claude-sonnet-4-6",
        system="You are Goldman.", messages=[],
        ctx=ctx, max_iterations=3,
    )
    assert result == "Hello from Goldman."


def test_agent_executes_tool_then_returns_followup_text():
    fake_claude = MagicMock()
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = "tool_1"
    tool_block.name = "who"
    tool_block.input = {}
    first_resp = MagicMock()
    first_resp.content = [tool_block]
    first_resp.stop_reason = "tool_use"

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Your company structure is..."
    second_resp = MagicMock()
    second_resp.content = [text_block]
    second_resp.stop_reason = "end_turn"

    fake_claude.messages.create.side_effect = [first_resp, second_resp]

    with patch("goldman.bot.agent.execute_tool", return_value="AMZ Expert Global..."):
        result = run_agent(
            claude=fake_claude, model="claude-sonnet-4-6",
            system="You are Goldman.", messages=[],
            ctx=MagicMock(), max_iterations=3,
        )

    assert result == "Your company structure is..."
    assert fake_claude.messages.create.call_count == 2
