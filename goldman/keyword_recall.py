"""Anthropic-only memory recall — pure keyword + recency, no embeddings.

Replaces the previous embedding-based path. For Goldman's volume (1000s of
facts at most), keyword matching plus a recency-ordered fallback gives
Claude enough context to reason well, with no OpenAI dependency.

Search semantics:
  1. Tokenize the query (lowercase, alphanumeric words >= 3 chars).
  2. Score facts by: # of matching tokens + 1 for a phrase match,
     break ties by recency.
  3. If still zero matches, return the most recent facts for the entity
     so Claude has SOMETHING to work with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from uuid import UUID


@dataclass(frozen=True)
class RecallResult:
    source_type: str
    source_id: UUID
    excerpt: str
    score: float
    entity_id: Optional[UUID]
    metadata: dict


_WORD_RE = re.compile(r"[a-z0-9]{3,}")


def _tokens(text: str) -> list:
    return _WORD_RE.findall(text.lower())


def keyword_recall(
    conn,
    *,
    query_text: str,
    entity_id: Optional[UUID] = None,
    top_n: int = 8,
    recency_fallback: bool = True,
) -> list:
    """Return ranked memory hits from goldman.facts_live + document_chunks.

    `entity_id` filters facts to the given entity OR NULL (cross-entity).
    Returns at most `top_n` results. When no keyword hits and
    `recency_fallback=True`, returns the most recent facts for context.
    """
    tokens = _tokens(query_text)
    phrase = query_text.strip()

    with conn.cursor() as cur:
        if entity_id is not None:
            cur.execute(
                """
                SELECT id, entity_id, kind, fact, created_at
                FROM goldman.facts_live
                WHERE (entity_id = %s OR entity_id IS NULL)
                ORDER BY created_at DESC
                LIMIT 500
                """,
                (entity_id,),
            )
        else:
            cur.execute(
                """
                SELECT id, entity_id, kind, fact, created_at
                FROM goldman.facts_live
                ORDER BY created_at DESC
                LIMIT 500
                """,
            )
        fact_rows = cur.fetchall()

        # Document chunks (already entity-scoped through documents.entity_id).
        # Wrapped in a savepoint so any schema mismatch can't poison the
        # caller's transaction.
        cur.execute("SAVEPOINT goldman_chunk_search")
        chunk_rows = []
        try:
            if entity_id is not None:
                cur.execute(
                    """
                    SELECT c.id, d.entity_id, c.text, c.chunk_index, d.filename
                    FROM goldman.document_chunks c
                    JOIN goldman.documents d ON d.id = c.document_id
                    WHERE d.entity_id = %s OR d.entity_id IS NULL
                    LIMIT 500
                    """,
                    (entity_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT c.id, d.entity_id, c.text, c.chunk_index, d.filename
                    FROM goldman.document_chunks c
                    JOIN goldman.documents d ON d.id = c.document_id
                    LIMIT 500
                    """,
                )
            chunk_rows = cur.fetchall()
            cur.execute("RELEASE SAVEPOINT goldman_chunk_search")
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT goldman_chunk_search")
            cur.execute("RELEASE SAVEPOINT goldman_chunk_search")
            chunk_rows = []

    scored = []
    for fid, ent, kind, fact, created_at in fact_rows:
        text_l = (fact or "").lower()
        toks_matched = sum(1 for t in tokens if t in text_l)
        phrase_hit = 1 if phrase and phrase.lower() in text_l else 0
        score = toks_matched + phrase_hit
        if score == 0:
            continue
        scored.append(RecallResult(
            source_type="fact",
            source_id=fid,
            excerpt=fact or "",
            score=float(score),
            entity_id=ent,
            metadata={"kind": kind, "created_at": str(created_at)},
        ))

    for cid, ent, text, idx, filename in chunk_rows:
        text_l = (text or "").lower()
        toks_matched = sum(1 for t in tokens if t in text_l)
        phrase_hit = 1 if phrase and phrase.lower() in text_l else 0
        score = toks_matched + phrase_hit
        if score == 0:
            continue
        scored.append(RecallResult(
            source_type="chunk",
            source_id=cid,
            excerpt=(text or "")[:500],
            score=float(score),
            entity_id=ent,
            metadata={"chunk_index": idx, "filename": filename},
        ))

    scored.sort(key=lambda r: (-r.score, -hash(r.source_id) % 10_000))
    if scored:
        return scored[:top_n]

    if not recency_fallback:
        return []

    return [
        RecallResult(
            source_type="fact",
            source_id=fid,
            excerpt=fact or "",
            score=0.0,
            entity_id=ent,
            metadata={"kind": kind, "created_at": str(created_at),
                      "fallback": "recency"},
        )
        for fid, ent, kind, fact, created_at in fact_rows[:top_n]
    ]
