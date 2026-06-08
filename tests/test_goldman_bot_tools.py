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


def test_execute_recall_runs_hybrid_search():
    ctx = MagicMock()
    ctx.entity_slug = "amzg"
    ctx.embedder.embed_batch.return_value = [[0.1] * 1536]
    ctx.conn = MagicMock()
    fake_results = [MagicMock(source_type="fact", source_id=uuid4(),
                              excerpt="hello", score=0.5, entity_id=None,
                              metadata={})]
    with patch("goldman.bot.tools.hybrid_search", return_value=fake_results), \
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
