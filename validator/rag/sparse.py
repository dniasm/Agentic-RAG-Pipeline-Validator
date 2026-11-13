"""BM25 keyword vectors for hybrid search.

Each chunk gets a sparse vector: {term id: BM25 term-frequency weight}. Qdrant multiplies in each term's
IDF (how rare it is across the collection) at query time via `Modifier.IDF`, so together they give the
standard BM25 score. Queries are sparse vectors with weight 1 per distinct term.

Tokenizer choices (they decide what "exact match" means):
- lowercase + Unicode normalisation, so "ＴＦ" == "tf" and the en-dash in "tf–idf" is handled;
- compound terms are split AND kept joined: "tf-idf" / "tf–idf" -> "tf", "idf", "tfidf",
  so "TF-IDF", "tf–idf" and "TFIDF" all match each other;
- decimals stay whole ("98.97"), so numbers can be matched exactly;
- common English stop words are dropped; no stemming (dense search already covers word forms).
"""
import re
import unicodedata
from collections import Counter

import mmh3
from qdrant_client import models

from validator.config import settings

_TOKEN = re.compile(r"[a-z0-9]+(?:[\-‐-―_/.][a-z0-9]+)*")
_COMPOUND_SPLIT = re.compile(r"[\-‐-―_/]")

STOP_WORDS = frozenset("""
a about above after again against all am an and any are as at be because been before being below between both
but by can could did do does doing down during each few for from further had has have having he her here hers
herself him himself his how i if in into is it its itself just me more most my myself no nor not now of off on
once only or other our ours ourselves out over own same she should so some such than that the their theirs them
themselves then there these they this those through to too under until up very was we were what when where which
while who whom why will with would you your yours yourself yourselves also may might must shall can't won't
""".split())


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower()
    tokens: list[str] = []
    for match in _TOKEN.finditer(text):
        token = match.group(0).strip(".")
        parts = [p for p in _COMPOUND_SPLIT.split(token) if p]
        if len(parts) > 1:
            tokens.extend(parts)
            tokens.append("".join(parts))  # tf-idf -> tfidf
        elif token:
            tokens.append(token)
    return [t for t in tokens if t not in STOP_WORDS and (len(t) > 1 or t.isdigit())]


def _term_id(term: str) -> int:
    return mmh3.hash(term, signed=False)  # stable 32-bit id per term (collisions are negligible)


def document_vector(text: str) -> models.SparseVector:
    """BM25 term-frequency part for a chunk; Qdrant applies IDF at query time."""
    counts = Counter(tokenize(text))
    length = sum(counts.values()) or 1
    k1, b, avg = settings.bm25_k1, settings.bm25_b, settings.bm25_avg_len
    norm = k1 * (1 - b + b * length / avg)
    weights: dict[int, float] = {}
    for term, tf in counts.items():
        idx = _term_id(term)
        weights[idx] = weights.get(idx, 0.0) + tf * (k1 + 1) / (tf + norm)
    return models.SparseVector(indices=list(weights), values=list(weights.values()))


def query_vector(text: str) -> models.SparseVector:
    ids = sorted({_term_id(t) for t in tokenize(text)})
    return models.SparseVector(indices=ids, values=[1.0] * len(ids))
