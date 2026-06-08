"""Token-aware text chunking using tiktoken (cl100k_base).

Returns chunks of <= max_tokens with overlap_tokens of overlap between
adjacent chunks. Whitespace is preserved; chunks may break mid-sentence.
"""

from __future__ import annotations

import tiktoken


_ENC = tiktoken.get_encoding("cl100k_base")


def chunk_text(
    text: str, *, max_tokens: int = 512, overlap_tokens: int = 64,
) -> list:
    if not text:
        return []

    tokens = _ENC.encode(text)
    if len(tokens) <= max_tokens:
        return [text]

    step = max_tokens - overlap_tokens
    if step <= 0:
        raise ValueError("overlap_tokens must be < max_tokens")

    chunks: list = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        slice_tokens = tokens[start:end]
        chunks.append(_ENC.decode(slice_tokens))
        if end == len(tokens):
            break
        start += step
    return chunks
