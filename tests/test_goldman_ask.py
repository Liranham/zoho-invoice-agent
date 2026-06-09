"""Tests for goldman.ask.ask_goldman — front-door-agnostic conversation entry."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from goldman.ask import ask_goldman


def _make_session(session_id="s-1", entity="amzg"):
    sess = MagicMock()
    sess.session_id = session_id
    sess.current_entity = entity
    return sess


def test_ask_goldman_runs_agent_and_persists_turns():
    with patch("goldman.ask.app_conn") as mock_conn, \
         patch("goldman.ask.GoldmanLLM") as mock_llm, \
         patch("goldman.ask.run_agent") as mock_run, \
         patch("goldman.ask.BotSessionRepository") as mock_bs_repo, \
         patch("goldman.ask.ConversationTurnRepository") as mock_turn_repo, \
         patch("goldman.ask.EntityRepository") as mock_ent_repo:
        mock_conn.return_value.__enter__.return_value = MagicMock()
        mock_llm.return_value._client = MagicMock()
        mock_llm.return_value.model = "claude-sonnet-4-6"
        mock_bs_repo.return_value.get_or_create.return_value = _make_session()
        mock_ent_repo.return_value.get_by_slug.return_value = MagicMock(id=uuid4())
        mock_turn_repo.return_value.list_by_session.return_value = []
        mock_run.return_value = "Hello, Liran."

        result = ask_goldman(
            question="who am I?",
            channel_id="liran-cc",
            front_door="claude-code",
        )

        assert result["answer"] == "Hello, Liran."
        assert result["entity"] == "amzg"
        assert result["session_id"] == "s-1"
        # Two turns inserted: user + assistant
        assert mock_turn_repo.return_value.insert.call_count == 2
        roles = [c.kwargs["role"] for c in mock_turn_repo.return_value.insert.call_args_list]
        assert roles == ["user", "assistant"]


def test_ask_goldman_replays_prior_turns_into_messages():
    prior = [
        MagicMock(role="user", text="what entities do we have?"),
        MagicMock(role="assistant", text="amzg and seo."),
    ]
    with patch("goldman.ask.app_conn") as mock_conn, \
         patch("goldman.ask.GoldmanLLM") as mock_llm, \
         patch("goldman.ask.run_agent") as mock_run, \
         patch("goldman.ask.BotSessionRepository") as mock_bs_repo, \
         patch("goldman.ask.ConversationTurnRepository") as mock_turn_repo, \
         patch("goldman.ask.EntityRepository") as mock_ent_repo:
        mock_conn.return_value.__enter__.return_value = MagicMock()
        mock_llm.return_value._client = MagicMock()
        mock_llm.return_value.model = "claude-sonnet-4-6"
        mock_bs_repo.return_value.get_or_create.return_value = _make_session()
        mock_ent_repo.return_value.get_by_slug.return_value = MagicMock(id=uuid4())
        mock_turn_repo.return_value.list_by_session.return_value = prior
        mock_run.return_value = "Both entities are still active."

        ask_goldman(question="and which is HK?", channel_id="liran-cc")

        sent_messages = mock_run.call_args.kwargs["messages"]
        # 2 prior turns are replayed before the new question is run through.
        assert sent_messages[0] == {"role": "user", "content": "what entities do we have?"}
        assert sent_messages[1] == {"role": "assistant", "content": "amzg and seo."}


def test_ask_goldman_raises_on_empty_question():
    with pytest.raises(ValueError):
        ask_goldman(question="   ", channel_id="x")


def test_ask_goldman_respects_explicit_entity_override():
    with patch("goldman.ask.app_conn") as mock_conn, \
         patch("goldman.ask.GoldmanLLM") as mock_llm, \
         patch("goldman.ask.run_agent") as mock_run, \
         patch("goldman.ask.BotSessionRepository") as mock_bs_repo, \
         patch("goldman.ask.ConversationTurnRepository") as mock_turn_repo, \
         patch("goldman.ask.EntityRepository") as mock_ent_repo:
        mock_conn.return_value.__enter__.return_value = MagicMock()
        mock_llm.return_value._client = MagicMock()
        mock_llm.return_value.model = "claude-sonnet-4-6"
        mock_bs_repo.return_value.get_or_create.return_value = _make_session(entity="amzg")
        mock_ent_repo.return_value.get_by_slug.return_value = MagicMock(id=uuid4())
        mock_turn_repo.return_value.list_by_session.return_value = []
        mock_run.return_value = "Switched to SEO."

        result = ask_goldman(
            question="what's the LLC's filing deadline?",
            channel_id="x",
            entity_slug="seo",
        )

        assert result["entity"] == "seo"
