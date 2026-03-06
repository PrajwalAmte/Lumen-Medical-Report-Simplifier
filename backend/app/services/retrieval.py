"""RAG retrieval service — pgvector + Jina AI embeddings.

Embeds parsed data via Jina API and queries PostgreSQL with pgvector
for cosine similarity search. Returns [] when RAG_ENABLED=false or
the embedding service is unavailable.
"""

import hashlib
from typing import Dict, List, Optional

import httpx
from sqlalchemy import text

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal

logger = get_logger("retrieval")

# Jina API endpoint
JINA_EMBED_URL = "https://api.jina.ai/v1/embeddings"

# Similarity threshold — cosine distance (1 - similarity); lower = more similar
SIMILARITY_THRESHOLD = 0.6


# ── Embedding via Jina AI ────────────────────────────────────────────


def _embed(texts: List[str]) -> List[List[float]]:
    """Embed texts using the Jina AI embeddings API."""
    if not settings.JINA_API_KEY:
        raise RuntimeError("JINA_API_KEY is not configured")

    headers = {
        "Authorization": f"Bearer {settings.JINA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.JINA_EMBEDDING_MODEL,
        "input": texts,
        "task": "text-matching",
        "dimensions": settings.JINA_DIMENSIONS,
        "late_chunking": False,
        "truncate": True,
    }

    response = httpx.post(
        JINA_EMBED_URL,
        json=payload,
        headers=headers,
        timeout=30.0,
    )
    response.raise_for_status()

    data = response.json()
    # Sort by index to ensure order matches input
    embeddings = sorted(data["data"], key=lambda x: x["index"])
    return [item["embedding"] for item in embeddings]


# ── Public API ────────────────────────────────────────────────────────


def retrieve_context(
    parsed_data: Dict,
    top_k: Optional[int] = None,
) -> List[str]:
    """Return the top-k knowledge chunks most relevant to parsed_data.
    Returns [] when RAG is disabled or the service is unavailable.
    """
    if not settings.RAG_ENABLED:
        return []

    top_k = top_k or settings.RAG_TOP_K

    try:
        query = _build_query(parsed_data)
        if not query:
            return []

        query_embedding = _embed([query])[0]

        db = SessionLocal()
        try:
            # pgvector cosine distance operator: <=>
            # Returns distance (0 = identical, 2 = opposite)
            result = db.execute(
                text("""
                    SELECT content, (embedding <=> :qvec::vector) AS distance
                    FROM medical_knowledge
                    ORDER BY embedding <=> :qvec::vector
                    LIMIT :top_k
                """),
                {"qvec": str(query_embedding), "top_k": top_k},
            )
            rows = result.fetchall()
        finally:
            db.close()

        # Filter by similarity threshold
        filtered = [row[0] for row in rows if row[1] < SIMILARITY_THRESHOLD]

        logger.info(
            "RAG retrieved %d/%d chunks (query=%s...)",
            len(filtered),
            len(rows),
            query[:60],
        )
        return filtered

    except Exception as e:
        logger.warning("RAG retrieval failed (graceful degrade): %s", e)
        return []


def _build_query(parsed_data: Dict) -> str:
    """Construct a semantic search query from parsed data."""
    parts = []

    for test in parsed_data.get("tests", []):
        name = test.get("name", "")
        value = test.get("value", "")
        unit = test.get("unit", "")
        parts.append(f"{name} {value} {unit}".strip())

    for med in parsed_data.get("medicines", []):
        name = med.get("name", "") if isinstance(med, dict) else str(med)
        parts.append(name)

    return " ".join(parts)


# ── Indexing (used by ingestion scripts) ─────────────────────────────


def index_documents(
    documents: List[str],
    metadatas: Optional[List[Dict]] = None,
    ids: Optional[List[str]] = None,
) -> int:
    """Embed documents via Jina and upsert into PostgreSQL. Returns count indexed."""
    if not documents:
        return 0

    if ids is None:
        ids = [hashlib.md5(doc.encode()).hexdigest() for doc in documents]

    if metadatas is None:
        metadatas = [{}] * len(documents)

    # Embed in batches of 64 (Jina API batch limit)
    batch_size = 64
    all_embeddings: List[List[float]] = []
    for i in range(0, len(documents), batch_size):
        batch = documents[i: i + batch_size]
        all_embeddings.extend(_embed(batch))

    db = SessionLocal()
    try:
        # Upsert: delete matching rows then insert fresh
        for i, (doc, emb, meta) in enumerate(zip(documents, all_embeddings, metadatas)):
            source = meta.get("source", "unknown")
            entity_id = meta.get("test_id") or meta.get("med_id") or ids[i]
            chunk_type = meta.get("chunk_type")

            db.execute(
                text("DELETE FROM medical_knowledge WHERE entity_id = :eid AND chunk_type IS NOT DISTINCT FROM :ct AND source = :src"),
                {"eid": entity_id, "ct": chunk_type, "src": source},
            )
            db.execute(
                text("""
                    INSERT INTO medical_knowledge (content, embedding, source, entity_id, chunk_type, metadata)
                    VALUES (:content, :embedding::vector, :source, :entity_id, :chunk_type, :metadata::jsonb)
                """),
                {
                    "content": doc,
                    "embedding": str(emb),
                    "source": source,
                    "entity_id": entity_id,
                    "chunk_type": chunk_type,
                    "metadata": "{}",
                },
            )

        db.commit()
        logger.info("Indexed %d documents into medical_knowledge table", len(documents))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return len(documents)


def reset_for_testing():
    """Reset module state (for tests)."""
    pass
