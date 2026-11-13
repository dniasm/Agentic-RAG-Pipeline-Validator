"""Qdrant vector store + Gemini embeddings.

Uses a Qdrant server when QDRANT_URL is set, otherwise an embedded on-disk store.
Each point has two named vectors:
  "dense" - Gemini embedding (meaning)
  "bm25"  - sparse BM25 keyword vector (see rag/sparse.py); Qdrant applies IDF at query time
Payloads follow the LangChain layout ({"page_content", "metadata"}).
"""
import threading
from functools import lru_cache

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from qdrant_client import QdrantClient, models

from validator.config import settings

# The embedded (local-path) Qdrant client is not safe for concurrent writers.
_lock = threading.RLock()


@lru_cache
def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model=settings.embedding_model,
        google_api_key=settings.gemini_api_key,
        output_dimensionality=settings.embedding_dim,
    )


def get_client() -> QdrantClient:
    # lru_cache alone isn't enough: two threads calling at once would both open the on-disk store, and the
    # second fails with "already accessed". (Validator change; day7 only ever opened it from one thread.)
    with _lock:
        return _open_client()


@lru_cache
def _open_client() -> QdrantClient:
    if settings.qdrant_url:
        client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    else:
        try:
            client = QdrantClient(path=settings.qdrant_path)
        except RuntimeError as e:
            if "already accessed" in str(e):
                raise RuntimeError(
                    "The local vector store is already in use by another validator process. "
                    "Only one can run at a time: close the portal server or the other command "
                    "(or end stray python.exe processes), then start again."
                ) from e
            raise
    _ensure_collection(client)
    return client


DENSE = "dense"
SPARSE = "bm25"


def _ensure_collection(client: QdrantClient) -> None:
    name = settings.collection_name
    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config={DENSE: models.VectorParams(size=settings.embedding_dim, distance=models.Distance.COSINE)},
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
    else:
        vectors = client.get_collection(name).config.params.vectors
        if not isinstance(vectors, dict) or DENSE not in vectors:
            raise RuntimeError(
                f"Collection '{name}' uses the old single-vector layout. Run "
                "`python -m backend.scripts.migrate_hybrid` or set COLLECTION_NAME to a new collection."
            )
        size = vectors[DENSE].size
        if size != settings.embedding_dim:
            raise RuntimeError(
                f"Collection '{name}' has vector size {size} but EMBEDDING_DIM={settings.embedding_dim}. "
                "Use a new COLLECTION_NAME or delete the old collection."
            )
    if settings.qdrant_url:
        # Payload indexes only matter (and are only supported) on a real server.
        for field in ("metadata.user_id", "metadata.doc_id"):
            client.create_payload_index(name, field_name=field, field_schema=models.PayloadSchemaType.KEYWORD)


def user_filter(user_id: str, doc_id: str | None = None) -> models.Filter:
    must = [models.FieldCondition(key="metadata.user_id", match=models.MatchValue(value=user_id))]
    if doc_id:
        must.append(models.FieldCondition(key="metadata.doc_id", match=models.MatchValue(value=doc_id)))
    return models.Filter(must=must)


def upsert(points: list[models.PointStruct]) -> None:
    client = get_client()
    with _lock:
        for i in range(0, len(points), 128):
            client.upsert(settings.collection_name, points=points[i:i + 128], wait=True)


def search_dense(vector: list[float], user_id: str, limit: int) -> list[models.ScoredPoint]:
    """Meaning search: score = cosine similarity."""
    client = get_client()
    with _lock:
        return client.query_points(
            settings.collection_name, query=vector, using=DENSE,
            query_filter=user_filter(user_id), limit=limit, with_payload=True,
        ).points


def search_sparse(vector: models.SparseVector, user_id: str, limit: int) -> list[models.ScoredPoint]:
    """Keyword (BM25) search: score = BM25. Also returns each hit's dense vector, so callers can
    compute the cosine similarity of keyword-only hits."""
    if not vector.indices:
        return []
    client = get_client()
    with _lock:
        return client.query_points(
            settings.collection_name, query=vector, using=SPARSE,
            query_filter=user_filter(user_id), limit=limit, with_payload=True, with_vectors=[DENSE],
        ).points


def get_dense_vectors(ids: list[str]) -> list[list[float] | None]:
    """Stored dense vectors for the given chunk ids (in the same order). No embedding requests."""
    client = get_client()
    with _lock:
        points = client.retrieve(settings.collection_name, ids=ids, with_vectors=[DENSE], with_payload=False)
    by_id = {str(p.id): (p.vector or {}).get(DENSE) if isinstance(p.vector, dict) else None for p in points}
    return [by_id.get(str(i)) for i in ids]


def delete_document_vectors(user_id: str, doc_id: str) -> None:
    client = get_client()
    with _lock:
        client.delete(
            settings.collection_name,
            points_selector=models.FilterSelector(filter=user_filter(user_id, doc_id)),
            wait=True,
        )


def count_user_vectors(user_id: str) -> int:
    client = get_client()
    with _lock:
        return client.count(settings.collection_name, count_filter=user_filter(user_id), exact=True).count


def close_client() -> None:
    """Close the shared Qdrant client during application shutdown."""
    with _lock:
        if _open_client.cache_info().currsize:
            _open_client().close()
            _open_client.cache_clear()
