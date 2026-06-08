"""Tests for EmbeddingClient + embed_pending_in."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from goldman.embeddings import (
    EmbeddingClient, EmbeddingConfigError, embed_pending_in,
)


def test_client_raises_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(EmbeddingConfigError):
        EmbeddingClient()


def test_embed_batch_returns_vectors_in_order(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    with patch("goldman.embeddings.openai.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = [
            MagicMock(embedding=[0.1, 0.2]),
            MagicMock(embedding=[0.3, 0.4]),
            MagicMock(embedding=[0.5, 0.6]),
        ]
        mock_client.embeddings.create.return_value = mock_resp
        mock_openai.return_value = mock_client

        client = EmbeddingClient()
        vectors = client.embed_batch(["a", "b", "c"])

        assert vectors == [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
        kwargs = mock_client.embeddings.create.call_args.kwargs
        assert kwargs["model"] == "text-embedding-3-small"


def test_embed_pending_in_processes_facts_turns_chunks(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    fake_facts = MagicMock()
    fake_facts.list_pending_embedding.side_effect = [
        [MagicMock(id=uuid4(), fact="UK VAT registered")],
        [],
    ]
    fake_turns = MagicMock()
    fake_turns.list_pending_embedding.return_value = []
    fake_chunks = MagicMock()
    fake_chunks.list_pending_embedding.return_value = []

    fake_embedder = MagicMock()
    fake_embedder.embed_batch.return_value = [[0.1] * 1536]

    summary = embed_pending_in(
        facts_repo=fake_facts,
        turns_repo=fake_turns,
        chunks_repo=fake_chunks,
        embedder=fake_embedder,
        batch_size=10,
    )

    fake_facts.set_embedding.assert_called_once()
    assert summary["facts"] == 1
    assert summary["turns"] == 0
    assert summary["chunks"] == 0
