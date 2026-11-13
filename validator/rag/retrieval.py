"""Multi-query retrieval scoped to a single user's documents.

mode="dense"  : meaning search only (Gemini embeddings, cosine similarity)
mode="hybrid" : meaning search + BM25 keyword search, fused with Reciprocal Rank Fusion (RRF):

    rrf(chunk) = sum over every ranked list the chunk appears in of  1 / (RRF_K + rank)

RRF combines *ranks*, not scores, so cosine similarities and BM25 scores (different scales) never
have to be compared. A chunk ranked highly by either search ends up near the top.

Every hit keeps its cosine similarity ("score"), including keyword-only hits, because the
"are the documents relevant at all?" decision is still based on it.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from validator.config import settings
from validator.rag import embedding_cache, sparse, vectorstore

log = logging.getLogger(__name__)


def _cosine(a, b) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / denom) if denom else 0.0


def _hit(p, query: str) -> dict:
    meta = p.payload.get("metadata", {})
    return {
        "id": str(p.id), "content": p.payload.get("page_content", ""), "source": meta.get("source"),
        "page": meta.get("page"), "doc_id": meta.get("doc_id"), "chunk_index": meta.get("chunk_index"),
        "score": 0.0, "rrf": 0.0, "dense_rank": None, "bm25_rank": None, "bm25": None, "matched_query": query,
    }


def retrieve(queries: list[str], user_id: str, k: int | None = None,
             min_score: float | None = None, mode: str | None = None) -> list[dict]:
    """Search every query variant and return the top k+2 chunks.

    Each hit: {"id", "content", "source", "page", "doc_id", "chunk_index", "matched_query",
               "score" (cosine), "rrf", "dense_rank", "bm25_rank", "bm25"}.
    """
    k = k or settings.retrieval_k
    mode = mode or settings.retrieval_mode
    min_score = settings.min_relevance_score if min_score is None else min_score
    queries = list(dict.fromkeys(q.strip() for q in queries if q and q.strip()))
    if not queries:
        return []

    hybrid = mode == "hybrid"
    try:
        with ThreadPoolExecutor(max_workers=min(4, len(queries))) as pool:
            vectors = list(pool.map(embedding_cache.embed_query, queries))  # each distinct question embedded once
    except Exception as e:
        if not hybrid:
            raise
        # Embedding service down or over quota: keyword search still works (it needs no embeddings).
        log.warning("Meaning search unavailable, using keyword search only: %s", str(e)[:200])
        vectors = [None] * len(queries)
    per_list = settings.hybrid_candidates if hybrid else k
    merged: dict[str, dict] = {}

    def add_ranked(points, query: str, kind: str):
        """Add one ranked list: every chunk earns 1/(RRF_K + rank) and remembers its best rank and score."""
        for rank, p in enumerate(points, start=1):
            hit = merged.setdefault(str(p.id), _hit(p, query))
            hit["rrf"] += 1.0 / (settings.rrf_k + rank)
            if kind == "dense":
                hit["dense_rank"] = min(rank, hit["dense_rank"] or rank)
                if p.score > hit["score"]:
                    hit["score"], hit["matched_query"] = round(float(p.score), 4), query
            else:
                hit["bm25_rank"] = min(rank, hit["bm25_rank"] or rank)
                hit["bm25"] = round(max(hit["bm25"] or 0.0, float(p.score)), 4)

    for query, vector in zip(queries, vectors):
        if vector is not None:
            dense = vectorstore.search_dense(vector, user_id, limit=per_list)
            add_ranked(dense, query, "dense")
        if hybrid:
            keyword = vectorstore.search_sparse(sparse.query_vector(query), user_id, limit=per_list)
            add_ranked(keyword, query, "bm25")
            if vector is None:
                continue
            # Keyword-only hits have no cosine score yet: compute it from their stored dense vector.
            for p in keyword:
                hit = merged[str(p.id)]
                dense_vec = (p.vector or {}).get(vectorstore.DENSE) if isinstance(p.vector, dict) else None
                if dense_vec is not None:
                    cos = round(_cosine(vector, dense_vec), 4)
                    if cos > hit["score"]:
                        hit["score"] = cos

    if hybrid:
        # Keep keyword matches even when their meaning-similarity is low: exact terms are the point of BM25.
        hits = [h for h in merged.values() if h["score"] >= min_score or h["bm25_rank"] is not None]
        hits.sort(key=lambda h: h["rrf"], reverse=True)
    else:
        hits = [h for h in merged.values() if h["score"] >= min_score]
        hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[: k + 2]  # a little headroom for the relevance check to discard noise
