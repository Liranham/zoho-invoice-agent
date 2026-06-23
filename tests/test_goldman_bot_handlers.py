"""Tests for the Telegram handlers."""

from __future__ import annotations

from goldman.bot.handlers import is_allowed_chat


def test_is_allowed_chat_matches_whitelist(monkeypatch):
    monkeypatch.setenv("GOLDMAN_BOT_ALLOWLIST_CHAT_IDS", "7884172049,12345")

    assert is_allowed_chat(7884172049) is True
    assert is_allowed_chat(12345) is True
    assert is_allowed_chat(99999) is False


def test_is_allowed_chat_denies_when_empty_allowlist(monkeypatch):
    monkeypatch.delenv("GOLDMAN_BOT_ALLOWLIST_CHAT_IDS", raising=False)
    assert is_allowed_chat(7884172049) is False


def test_goldman_persona_explains_pack_citation():
    from goldman.bot.handlers import GOLDMAN_PERSONA
    assert "knowledge_pack" in GOLDMAN_PERSONA or "knowledge pack" in GOLDMAN_PERSONA.lower()
    assert "pack_topic" in GOLDMAN_PERSONA or "topic" in GOLDMAN_PERSONA.lower()
    assert "uploaded" in GOLDMAN_PERSONA.lower() or "letter" in GOLDMAN_PERSONA.lower()


def test_goldman_persona_mentions_recall_decisions_tool():
    from goldman.bot.handlers import GOLDMAN_PERSONA
    assert "recall_decisions" in GOLDMAN_PERSONA
    assert "decide" in GOLDMAN_PERSONA.lower()


# --- Context understanding: identify the company from what the user typed ---
from types import SimpleNamespace  # noqa: E402

from goldman.bot.handlers import _entity_from_text  # noqa: E402


def _entities():
    return [
        SimpleNamespace(slug="amzg", legal_name="AMZ-Expert Global Limited"),
        SimpleNamespace(slug="seo", legal_name="Pacific Edge Outsourcing LLC"),
    ]


def test_entity_from_text_matches_pacific_edge_nickname():
    # The exact phrasing from the real chat that used to be ignored.
    txt = "This is the 2025 Pacific edge LLC wise statement please save it on drive"
    assert _entity_from_text(txt, _entities()) == "seo"


def test_entity_from_text_matches_full_and_partial_names():
    ents = _entities()
    assert _entity_from_text("file this under AMZ-Expert Global please", ents) == "amzg"
    assert _entity_from_text("pacific edge", ents) == "seo"
    assert _entity_from_text("it's for the HK company", ents) == "amzg"


def test_entity_from_text_matches_bare_slug():
    assert _entity_from_text("put it on seo", _entities()) == "seo"


def test_entity_from_text_none_when_unnamed():
    assert _entity_from_text("save it to drive please", _entities()) is None
    assert _entity_from_text("", _entities()) is None
