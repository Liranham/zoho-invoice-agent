"""OpenAI embedding client + batch worker for goldman pending rows."""

from __future__ import annotations

import os
from typing import Optional

import openai


DEFAULT_MODEL = "text-embedding-3-small"


class EmbeddingConfigError(RuntimeError):
    """Raised when the OpenAI API key is missing."""


class EmbeddingClient:
    def __init__(self, *, model: str = DEFAULT_MODEL):
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise EmbeddingConfigError(
                "OPENAI_API_KEY not set. Goldman embeddings need it."
            )
        self._client = openai.OpenAI(api_key=api_key)
        self.model = model

    def embed_batch(self, texts: list) -> list:
        if not texts:
            return []
        resp = self._client.embeddings.create(
            model=self.model,
            input=texts,
            encoding_format="float",
        )
        return [list(d.embedding) for d in resp.data]


def embed_pending_in(
    *,
    facts_repo,
    turns_repo,
    chunks_repo,
    embedder: EmbeddingClient,
    batch_size: int = 50,
) -> dict:
    """Embed all rows with NULL embeddings across facts, turns, chunks.

    Returns a summary dict {facts: N, turns: N, chunks: N}.
    """
    summary = {"facts": 0, "turns": 0, "chunks": 0}

    # FACTS
    facts = facts_repo.list_pending_embedding(limit=batch_size)
    while facts:
        texts = [f.fact for f in facts]
        vectors = embedder.embed_batch(texts)
        for f, v in zip(facts, vectors):
            facts_repo.set_embedding(f.id, v)
            summary["facts"] += 1
        facts = facts_repo.list_pending_embedding(limit=batch_size)

    # TURNS
    turns = turns_repo.list_pending_embedding(limit=batch_size)
    while turns:
        texts = [t.text for t in turns]
        vectors = embedder.embed_batch(texts)
        for t, v in zip(turns, vectors):
            turns_repo.set_embedding(t.id, v)
            summary["turns"] += 1
        turns = turns_repo.list_pending_embedding(limit=batch_size)

    # CHUNKS
    chunks = chunks_repo.list_pending_embedding(limit=batch_size)
    while chunks:
        texts = [c.text for c in chunks]
        vectors = embedder.embed_batch(texts)
        for c, v in zip(chunks, vectors):
            chunks_repo.set_embedding(c.id, v)
            summary["chunks"] += 1
        chunks = chunks_repo.list_pending_embedding(limit=batch_size)

    return summary
