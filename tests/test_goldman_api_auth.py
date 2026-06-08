"""Tests for the API auth check."""

from __future__ import annotations

from goldman.api.auth import is_authorized


def test_is_authorized_accepts_matching_bearer(monkeypatch):
    monkeypatch.setenv("GOLDMAN_API_KEY", "secret_xyz")
    assert is_authorized({"Authorization": "Bearer secret_xyz"}) is True


def test_is_authorized_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("GOLDMAN_API_KEY", "secret_xyz")
    assert is_authorized({"Authorization": "Bearer nope"}) is False


def test_is_authorized_rejects_missing_header(monkeypatch):
    monkeypatch.setenv("GOLDMAN_API_KEY", "secret_xyz")
    assert is_authorized({}) is False


def test_is_authorized_denies_when_key_not_set(monkeypatch):
    monkeypatch.delenv("GOLDMAN_API_KEY", raising=False)
    assert is_authorized({"Authorization": "Bearer anything"}) is False
