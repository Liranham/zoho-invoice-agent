"""Tests for the Goldman tool registry."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from goldman.bot.tools import TOOL_SCHEMAS, execute_tool


def test_tool_schemas_have_expected_names():
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert "recall" in names
    assert "who" in names
    assert "remember_fact" in names
    assert "list_invoices" in names
    assert "list_pending_confirmations" in names


def test_execute_recall_runs_keyword_recall():
    ctx = MagicMock()
    ctx.entity_slug = "amzg"
    ctx.conn = MagicMock()
    fake_results = [MagicMock(source_type="fact", source_id=uuid4(),
                              excerpt="hello", score=2.0, entity_id=None,
                              metadata={})]
    with patch("goldman.bot.tools.keyword_recall", return_value=fake_results), \
         patch("goldman.bot.tools.EntityRepository") as mock_er:
        mock_er.return_value.get_by_slug.return_value = MagicMock(id=uuid4())
        result = execute_tool(
            ctx=ctx, name="recall",
            arguments={"question": "what about VAT?"},
        )
    assert "hello" in result or "fact" in result


def test_execute_unknown_tool_raises():
    ctx = MagicMock()
    with pytest.raises(ValueError, match="Unknown tool"):
        execute_tool(ctx=ctx, name="not_a_tool", arguments={})


def test_recall_decisions_is_in_tool_schemas():
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert "recall_decisions" in names
    schema = next(t for t in TOOL_SCHEMAS if t["name"] == "recall_decisions")
    assert "topic" in schema["input_schema"]["properties"]


def test_execute_recall_decisions_returns_formatted_timeline():
    ctx = MagicMock()
    ctx.entity_slug = "amzg"
    ctx.conn = MagicMock()
    fake_results = [
        {"id": uuid4(),
         "fact": "Hire UK accountant for VAT filings",
         "entity_slug": "amzg",
         "created_at": "2026-06-08T00:00:00+00:00",
         "supersedes_id": None},
    ]
    with patch("goldman.bot.tools.decision_timeline", return_value=fake_results):
        result = execute_tool(
            ctx=ctx, name="recall_decisions",
            arguments={"topic": "VAT"},
        )
    assert "VAT" in result or "Decision timeline" in result
    assert "Hire UK accountant" in result
    assert "2026-06-08" in result
    assert "amzg" in result


def test_execute_recall_decisions_empty_results_returns_no_matches_message():
    ctx = MagicMock()
    ctx.entity_slug = "amzg"
    ctx.conn = MagicMock()
    with patch("goldman.bot.tools.decision_timeline", return_value=[]):
        result = execute_tool(
            ctx=ctx, name="recall_decisions",
            arguments={"topic": "nothing"},
        )
    assert "No prior decisions" in result or "no decisions" in result.lower()
