"""Tests for chunk_text."""

from __future__ import annotations

from goldman.chunker import chunk_text


def test_short_text_returns_one_chunk():
    chunks = chunk_text("hello world", max_tokens=512, overlap_tokens=64)
    assert chunks == ["hello world"]


def test_long_text_splits_with_overlap():
    text = ("the cat sat on the mat " * 1500).strip()
    chunks = chunk_text(text, max_tokens=512, overlap_tokens=64)
    assert len(chunks) >= 3
    assert all(c.strip() for c in chunks)


def test_overlap_creates_shared_prefix_suffix():
    text = " ".join(f"word{i}" for i in range(2000))
    chunks = chunk_text(text, max_tokens=200, overlap_tokens=20)
    if len(chunks) >= 2:
        tail = chunks[0].split()[-5:]
        head = chunks[1].split()[:30]
        assert any(w in head for w in tail)
