"""Tests for SupabaseStorage."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from goldman.storage import SupabaseStorage, StorageConfigError


def test_raises_when_env_missing(monkeypatch):
    monkeypatch.delenv("GOLDMAN_SUPABASE_URL", raising=False)
    monkeypatch.delenv("GOLDMAN_SUPABASE_SERVICE_KEY", raising=False)

    with pytest.raises(StorageConfigError):
        SupabaseStorage()


def test_upload_sends_put_with_service_key(monkeypatch):
    monkeypatch.setenv("GOLDMAN_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("GOLDMAN_SUPABASE_SERVICE_KEY", "sk_test")

    with patch("goldman.storage.requests.put") as mock_put:
        mock_put.return_value.status_code = 200
        mock_put.return_value.raise_for_status = MagicMock()

        s = SupabaseStorage()
        s.upload(
            bucket="goldman-documents",
            path="amzg/2026/foo.pdf",
            content=b"%PDF...",
            content_type="application/pdf",
        )

        args, kwargs = mock_put.call_args
        assert "goldman-documents/amzg/2026/foo.pdf" in args[0]
        assert kwargs["headers"]["Authorization"] == "Bearer sk_test"
        assert kwargs["headers"]["Content-Type"] == "application/pdf"
        assert kwargs["data"] == b"%PDF..."


def test_download_returns_response_body(monkeypatch):
    monkeypatch.setenv("GOLDMAN_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("GOLDMAN_SUPABASE_SERVICE_KEY", "sk_test")

    with patch("goldman.storage.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.content = b"file bytes"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        s = SupabaseStorage()
        body = s.download(bucket="goldman-documents", path="amzg/x.pdf")

        assert body == b"file bytes"
