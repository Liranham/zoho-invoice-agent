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
