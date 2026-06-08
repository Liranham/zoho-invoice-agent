-- Goldman hybrid_search: RRF fusion of vector + keyword across all
-- searchable surfaces (facts, conversation_turns, document_chunks).
-- Per spec §6.3.

CREATE OR REPLACE FUNCTION goldman.hybrid_search(
    p_query_embedding vector(1536),
    p_query_text       TEXT,
    p_entity_id        UUID    DEFAULT NULL,
    p_top_n            INTEGER DEFAULT 20,
    p_rrf_k            INTEGER DEFAULT 60
) RETURNS TABLE (
    source_type TEXT,
    source_id   UUID,
    excerpt     TEXT,
    score       FLOAT,
    entity_id   UUID,
    metadata    JSONB
) LANGUAGE sql STABLE AS $$
WITH
-- VECTOR leg: union all sources, rank globally by cosine distance.
vector_pool AS (
    SELECT 'fact'::TEXT AS source_type, f.id AS source_id,
           f.fact AS excerpt, f.entity_id,
           jsonb_build_object('kind', f.kind, 'source', f.source) AS metadata,
           (f.embedding <=> p_query_embedding) AS distance
    FROM goldman.facts_live f
    WHERE f.embedding IS NOT NULL
      AND (p_entity_id IS NULL OR f.entity_id = p_entity_id OR f.entity_id IS NULL)
    UNION ALL
    SELECT 'turn', t.id, t.text, t.entity_id,
           jsonb_build_object('role', t.role, 'session_id', t.session_id,
                              'front_door', t.front_door),
           (t.embedding <=> p_query_embedding)
    FROM goldman.conversation_turns t
    WHERE t.embedding IS NOT NULL
      AND (p_entity_id IS NULL OR t.entity_id = p_entity_id OR t.entity_id IS NULL)
    UNION ALL
    SELECT 'chunk', c.id, c.text, d.entity_id,
           jsonb_build_object('document_id', d.id, 'filename', d.filename,
                              'chunk_index', c.chunk_index),
           (c.embedding <=> p_query_embedding)
    FROM goldman.document_chunks c
    JOIN goldman.documents d ON d.id = c.document_id
    WHERE c.embedding IS NOT NULL
      AND (p_entity_id IS NULL OR d.entity_id = p_entity_id OR d.entity_id IS NULL)
),
vector_ranked AS (
    SELECT source_type, source_id, excerpt, entity_id, metadata,
           ROW_NUMBER() OVER (ORDER BY distance) AS rk
    FROM vector_pool
    ORDER BY distance
    LIMIT p_top_n * 3
),
-- KEYWORD leg: full-text search, same shape.
keyword_pool AS (
    SELECT 'fact'::TEXT AS source_type, f.id AS source_id,
           f.fact AS excerpt, f.entity_id,
           jsonb_build_object('kind', f.kind, 'source', f.source) AS metadata,
           ts_rank_cd(to_tsvector('english', f.fact),
                      plainto_tsquery('english', p_query_text)) AS rank_score
    FROM goldman.facts_live f
    WHERE to_tsvector('english', f.fact) @@ plainto_tsquery('english', p_query_text)
      AND (p_entity_id IS NULL OR f.entity_id = p_entity_id OR f.entity_id IS NULL)
    UNION ALL
    SELECT 'turn', t.id, t.text, t.entity_id,
           jsonb_build_object('role', t.role, 'session_id', t.session_id,
                              'front_door', t.front_door),
           ts_rank_cd(to_tsvector('english', t.text),
                      plainto_tsquery('english', p_query_text))
    FROM goldman.conversation_turns t
    WHERE to_tsvector('english', t.text) @@ plainto_tsquery('english', p_query_text)
      AND (p_entity_id IS NULL OR t.entity_id = p_entity_id OR t.entity_id IS NULL)
    UNION ALL
    SELECT 'chunk', c.id, c.text, d.entity_id,
           jsonb_build_object('document_id', d.id, 'filename', d.filename,
                              'chunk_index', c.chunk_index),
           ts_rank_cd(to_tsvector('english', c.text),
                      plainto_tsquery('english', p_query_text))
    FROM goldman.document_chunks c
    JOIN goldman.documents d ON d.id = c.document_id
    WHERE to_tsvector('english', c.text) @@ plainto_tsquery('english', p_query_text)
      AND (p_entity_id IS NULL OR d.entity_id = p_entity_id OR d.entity_id IS NULL)
),
keyword_ranked AS (
    SELECT source_type, source_id, excerpt, entity_id, metadata,
           ROW_NUMBER() OVER (ORDER BY rank_score DESC) AS rk
    FROM keyword_pool
    ORDER BY rank_score DESC
    LIMIT p_top_n * 3
),
-- RRF fusion: each row's score is sum over rankers of 1/(k + rank).
-- Within a single (source_type, source_id) all rows have identical
-- excerpt/entity_id/metadata, so MAX() / array_agg()[1] are safe picks.
combined AS (
    SELECT source_type, source_id,
           MAX(excerpt) AS excerpt,
           MAX(entity_id) AS entity_id,
           (array_agg(metadata))[1] AS metadata,
           SUM(1.0 / (p_rrf_k + rk))::FLOAT AS total_score
    FROM (
        SELECT source_type, source_id, excerpt, entity_id, metadata, rk
        FROM vector_ranked
        UNION ALL
        SELECT source_type, source_id, excerpt, entity_id, metadata, rk
        FROM keyword_ranked
    ) u
    GROUP BY source_type, source_id
)
SELECT source_type, source_id, excerpt, total_score AS score,
       entity_id, metadata
FROM combined
ORDER BY total_score DESC
LIMIT p_top_n;
$$;

-- goldman_app_login inherits goldman_app; both can call this function.
GRANT EXECUTE ON FUNCTION goldman.hybrid_search(vector, TEXT, UUID, INTEGER, INTEGER) TO goldman_app;
