"""Stage 2: reranking, confidence zones, and MMR selection.

A reranker reads the question and a passage TOGETHER and scores how well the passage answers it (more
accurate than comparing two separately computed vectors). Two providers:

    voyage  hosted (Voyage AI rerank API): no torch, no model in memory, so the app can be deployed on a
            small server. The default.
    local   cross-encoder (ms-marco-MiniLM-L-6-v2) running on this machine: no API, but ~450 MB of RAM
            and torch. Used when RERANKER_PROVIDER=local, or as a backup for Voyage when
            RERANKER_LOCAL_FALLBACK=true.

If no reranker can score (Voyage down or rate-limited and no local model), score() returns None and the
caller falls back to the LLM relevance check.

The best score is the "confidence" that decides whether the documents cover a question. Each provider
scores on its own scale, so each has its own thresholds (calibrated on the benchmark):

    best relevance >= high  -> "high": answer from the documents
    between the two         -> "mid":  something related exists; reword and search once more
    best relevance <  low   -> "low":  the documents don't cover it; go to the next source

MMR (Maximal Marginal Relevance) then picks the final passages one at a time, each time taking the one
that maximises   lambda * relevance - (1 - lambda) * (max similarity to passages already picked),
so near-duplicates (our chunks overlap by 200 characters) don't crowd out other useful passages.
"""
import logging
import math
import threading
import time
from functools import lru_cache

import numpy as np

from validator.config import settings

log = logging.getLogger(__name__)

PASSAGE_CHARS = 2000  # characters of each passage sent to the reranker

_model = None
_load_failed = False
_lock = threading.Lock()


# ---------------------------------------------------------------- local cross-encoder
def _load():
    global _model, _load_failed
    with _lock:
        if _model is not None or _load_failed:
            return
        try:
            from sentence_transformers import CrossEncoder
            kwargs = {"max_length": settings.reranker_max_length}
            try:  # use the downloaded copy if there is one: no network checks, works offline
                _model = CrossEncoder(settings.reranker_model, local_files_only=True, **kwargs)
            except Exception:  # first run: download it (~90 MB, once)
                _model = CrossEncoder(settings.reranker_model, **kwargs)
            log.info("Local cross-encoder %s loaded", settings.reranker_model)
        except Exception as e:  # missing package, no network on first download, ...
            _load_failed = True
            log.warning("Local cross-encoder unavailable: %s", e)


def _wants_local() -> bool:
    return settings.reranker_provider == "local" or settings.reranker_local_fallback


def _voyage_configured() -> bool:
    return settings.reranker_provider == "voyage" and bool(settings.voyage_api_key)


def warm_up_in_background() -> None:
    """Load the local model at startup only if it will be used (loading torch can take a minute)."""
    if settings.rerank_enabled and _wants_local():
        threading.Thread(target=_load, name="cross-encoder-loader", daemon=True).start()


def available() -> bool:
    """A reranker can be tried for this request."""
    return settings.rerank_enabled and (_voyage_configured() or _model is not None)


def ensure_loaded() -> bool:
    """Make the configured reranker ready now (benchmark and scripts)."""
    if settings.rerank_enabled and _wants_local():
        _load()
    return available()


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _score_local(query: str, texts: list[str]) -> list[float]:
    logits = _model.predict([(query, t) for t in texts], batch_size=32, show_progress_bar=False)
    return [_sigmoid(float(x)) for x in logits]


# ---------------------------------------------------------------- Voyage
@lru_cache(maxsize=1)
def _voyage_client():
    import voyageai
    # One quick retry for a dropped connection; rate limits are handled by the fallback, not by waiting.
    return voyageai.Client(api_key=settings.voyage_api_key, max_retries=1, timeout=settings.voyage_rerank_timeout)


def _score_voyage(query: str, texts: list[str]) -> list[float]:
    result = _voyage_client().rerank(query, texts, model=settings.voyage_rerank_model, truncation=True)
    scores = [0.0] * len(texts)
    for r in result.results:
        scores[r.index] = float(r.relevance_score)
    return scores


# ---------------------------------------------------------------- scoring and zones
def score(query: str, hits: list[dict]) -> list[dict] | None:
    """Attach "relevance" (0-1) and "scorer" to each hit and return them sorted best first.
    Returns None if no reranker could score them (the caller then uses the LLM relevance check)."""
    if not hits:
        return []
    texts = [h["content"][:PASSAGE_CHARS] for h in hits]
    attempts = []
    if _voyage_configured():
        attempts.append(("voyage", _score_voyage))
    if _wants_local() and _model is not None:
        attempts.append(("local", _score_local))
    for name, scorer in attempts:
        started = time.perf_counter()
        try:
            scores = scorer(query, texts)
        except Exception as e:  # rate limit, network, service error
            log.warning("Reranker %s failed (%s): %s", name, type(e).__name__, str(e)[:200])
            continue
        log.info("Reranked %d passages with %s in %.2fs", len(hits), name, time.perf_counter() - started)
        for h, s in zip(hits, scores):
            h["relevance"], h["scorer"] = round(s, 4), name
        return sorted(hits, key=lambda h: h["relevance"], reverse=True)
    return None


def thresholds(scorer: str | None = None) -> tuple[float, float]:
    """(high, low) for the scorer that produced the scores."""
    if (scorer or settings.reranker_provider) == "voyage":
        return settings.voyage_relevance_high, settings.voyage_relevance_low
    return settings.relevance_high, settings.relevance_low


def zone(best_relevance: float | None, scorer: str | None = None) -> str:
    high, low = thresholds(scorer)
    if best_relevance is None or best_relevance < low:
        return "low"
    return "high" if best_relevance >= high else "mid"


# ---------------------------------------------------------------- MMR
def _cos_matrix(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    unit = vectors / np.where(norms == 0, 1, norms)
    return unit @ unit.T


def mmr_select(hits: list[dict], k: int | None = None, lam: float | None = None) -> list[dict]:
    """Pick k passages from the reranked hits, trading relevance against redundancy."""
    from validator.rag import vectorstore

    k = k or settings.retrieval_k
    lam = settings.mmr_lambda if lam is None else lam
    pool = hits[: settings.rerank_top_n]
    if len(pool) <= 1:
        return pool
    vectors = vectorstore.get_dense_vectors([h["id"] for h in pool])
    if any(v is None for v in vectors):  # can't measure redundancy: keep the relevance order
        return pool[:k]
    sim = _cos_matrix(np.asarray(vectors, dtype=float))
    rel = np.array([h["relevance"] for h in pool])
    chosen = [0]  # the most relevant passage always goes first
    while len(chosen) < min(k, len(pool)):
        rest = [i for i in range(len(pool)) if i not in chosen]
        best = max(rest, key=lambda i: lam * rel[i] - (1 - lam) * max(sim[i][j] for j in chosen))
        chosen.append(best)
    return [pool[i] for i in chosen]
