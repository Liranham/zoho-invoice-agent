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
