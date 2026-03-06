"""
RAG retrieval service — embeds parsed data and queries ChromaDB.
Gracefully returns [] when RAG_ENABLED=false or ChromaDB is unavailable.
"""

import hashlib
from typing import Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("retrieval")

_client = None
_collection = None
_embed_fn = None


def _get_chromadb_client():
    """Lazily initialise and return the ChromaDB HTTP client."""
    global _client
    if _client is None:
        import chromadb

        _client = chromadb.HttpClient(
            host=settings.CHROMADB_HOST,
            port=settings.CHROMADB_PORT,
        )
        logger.info(
            "ChromaDB client initialised → %s:%s",
            settings.CHROMADB_HOST,
            settings.CHROMADB_PORT,
        )
    return _client


def _get_collection():
    """Get-or-create the Lumen ChromaDB collection."""
    global _collection
    if _collection is None:
        client = _get_chromadb_client()
        _collection = client.get_or_create_collection(
            name=settings.CHROMADB_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "ChromaDB collection '%s' ready (%d docs)",
            settings.CHROMADB_COLLECTION,
            _collection.count(),
        )
    return _collection


def _get_embedding_function():
    """Lazily load the sentence-transformers embedding model."""
    global _embed_fn
    if _embed_fn is None:
        from sentence_transformers import SentenceTransformer

        _embed_fn = SentenceTransformer(settings.EMBEDDING_MODEL)
        logger.info("Loaded embedding model: %s", settings.EMBEDDING_MODEL)
    return _embed_fn


def _embed(texts: List[str]) -> List[List[float]]:
    """Embed texts using the loaded SentenceTransformer model."""
    model = _get_embedding_function()
    embeddings = model.encode(texts, show_progress_bar=False)
    return embeddings.tolist()


# ── Public API ────────────────────────────────────────────────────────


def retrieve_context(
    parsed_data: Dict,
    top_k: Optional[int] = None,
) -> List[str]:
    """Return the top-k knowledge chunks most relevant to parsed_data.
    Returns [] when RAG is disabled or ChromaDB is unavailable.
    """
    if not settings.RAG_ENABLED:
        return []

    top_k = top_k or settings.RAG_TOP_K

    try:
        query = _build_query(parsed_data)
        if not query:
            return []

        collection = _get_collection()
        query_embedding = _embed([query])

        results = collection.query(
            query_embeddings=query_embedding,
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]

        # Filter by similarity threshold (cosine distance < 0.6)
        filtered = []
        for doc, dist in zip(documents, distances):
            if dist < 0.6:
                filtered.append(doc)

        logger.info(
            "RAG retrieved %d/%d chunks (query=%s...)",
            len(filtered),
            len(documents),
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
    """Embed and upsert documents into ChromaDB. Returns count indexed.
    IDs are auto-generated from MD5 of content if not provided.
    """
    if not documents:
        return 0

    if ids is None:
        ids = [
            hashlib.md5(doc.encode()).hexdigest()
            for doc in documents
        ]

    if metadatas is None:
        metadatas = [{}] * len(documents)

    embeddings = _embed(documents)
    collection = _get_collection()

    batch_size = 100  # upsert in batches to avoid request size limits
    total = 0
    for i in range(0, len(documents), batch_size):
        batch_docs = documents[i: i + batch_size]
        batch_ids = ids[i: i + batch_size]
        batch_meta = metadatas[i: i + batch_size]
        batch_emb = embeddings[i: i + batch_size]

        collection.upsert(
            ids=batch_ids,
            documents=batch_docs,
            metadatas=batch_meta,
            embeddings=batch_emb,
        )
        total += len(batch_docs)

    logger.info("Indexed %d documents into '%s'", total, settings.CHROMADB_COLLECTION)
    return total


def reset_for_testing():
    """Reset module-level singletons (for tests)."""
    global _client, _collection, _embed_fn
    _client = None
    _collection = None
    _embed_fn = None
