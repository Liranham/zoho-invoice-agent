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


def _tool_use_resp(idx):
    b = MagicMock()
    b.type = "tool_use"
    b.id = f"tool_{idx}"
    b.name = "recall"
    b.input = {}
    r = MagicMock()
    r.content = [b]
    r.stop_reason = "tool_use"
    return r


def test_agent_forces_final_answer_when_iterations_exhausted():
    """If every step asks for a tool, the loop must still return a real
    plain-text answer (one final tools-disabled call), never the old
    dead-end 'tool-iteration cap' string."""
    fake_claude = MagicMock()

    final_text = MagicMock()
    final_text.type = "text"
    final_text.text = "Yes — I have the Wise 2025 statement. Here's the summary."
    final_resp = MagicMock()
    final_resp.content = [final_text]
    final_resp.stop_reason = "end_turn"

    # 2 tool-use rounds (exhaust max_iterations=2), then the forced wrap-up.
    fake_claude.messages.create.side_effect = [
        _tool_use_resp(1), _tool_use_resp(2), final_resp,
    ]

    ctx = MagicMock()
    ctx.conn = None  # skip savepoint plumbing in this unit test
    with patch("goldman.bot.agent.execute_tool", return_value="some rows"):
        result = run_agent(
            claude=fake_claude, model="claude-sonnet-4-6",
            system="You are Goldman.", messages=[],
            ctx=ctx, max_iterations=2,
        )

    assert "Wise 2025 statement" in result
    assert "tool-iteration cap" not in result
    # 2 in-loop calls + 1 forced final call.
    assert fake_claude.messages.create.call_count == 3
    # The final call must have NO tools available.
    assert "tools" not in fake_claude.messages.create.call_args.kwargs
