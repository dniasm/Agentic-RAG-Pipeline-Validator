"""The base agent: day7's document-answer path, without the router.

    hybrid search -> rerank (Voyage) -> confidence zone -> MMR -> grounded answer with [n] citations
    -> code citation check (no model)

Prompt, search, reranking, thresholds and MMR are day7's. Two deliberate differences, so that only the base
model is ever called:
  - no query rewrite or second search in the "mid" zone (day7 uses gpt-oss-20b for that); mid-zone passages
    are answered from directly, and the zone is recorded;
  - no LLM answer check (day7 uses gpt-oss-120b); the judges do the checking instead.
When the reranker finds nothing relevant ("low" zone), the agent says the documents don't cover the question,
as day7 does before it would move on to another source.
"""
import logging
import re
import time

from validator import models
from validator.config import settings
from validator.rag import citations, rerank, retrieval

log = logging.getLogger(__name__)

NO_ANSWER = "NO_ANSWER_IN_DOCUMENTS"
NOT_COVERED = "The documents don't contain an answer to this question."

# day7 backend/tools/__init__.py: FORMAT_RULES
FORMAT_RULES = (
    "Use concise, natural prose by default. Answer the exact question first. "
    "For simple questions and conversational follow-ups, usually respond in "
    "1–3 sentences. Expand only when the question genuinely requires detail. "
    "Do not add headings, tables, lists, alternative viewpoints, objections, "
    "or a separate conclusion unless they materially improve the answer. "
    "Use GitHub-flavored Markdown when useful. No HTML. Cite sources only as [n]."
    " For follow-up questions, address the specific challenge or new information "
    "rather than restating the previous answer."
)

# day7 backend/tools/rag.py: SYSTEM
SYSTEM = """You answer questions using ONLY the provided document excerpts from the user's knowledge base.

Rules:
- Ground every claim in the excerpts. Cite them inline with their bracket number, e.g. [1] or [2][3].
- If the excerpts only partially answer the question, answer what you can and state clearly
  what is not covered by the documents.
- If the excerpts contain nothing that answers the question, reply with exactly {NO_ANSWER} and nothing else.
- Never use outside knowledge to fill gaps.
- Be concise and well structured.

{FORMAT_RULES}""".replace("{NO_ANSWER}", NO_ANSWER).replace("{FORMAT_RULES}", FORMAT_RULES)

_CITE = re.compile(r"【(\d+)(?:†[^】]*)?】")


def _clean(text: str) -> str:
    """gpt-oss writes citations as 【1†L1-L3】; normalise them to [1] (day7 clean_answer)."""
    return _CITE.sub(r"[\1]", text).strip()


def format_context(docs: list[dict]) -> str:
    blocks = []
    for i, d in enumerate(docs, start=1):
        page = f", page {d['page']}" if d.get("page") else ""
        blocks.append(f"[{i}] (source: {d['source']}{page})\n{d['content']}")
    return "\n\n".join(blocks)


def _rerank_with_patience(question: str, hits: list[dict]) -> list[dict] | None:
    """Voyage's free tier allows 3 requests a minute; wait and retry rather than change the pipeline."""
    for wait in (0, 25, 40):
        if wait:
            log.info("Reranker unavailable, retrying in %ds", wait)
            time.sleep(wait)
        ranked = rerank.score(question, hits)
        if ranked is not None:
            return ranked
    return None


def retrieve_passages(question: str) -> dict:
    """Search and select passages exactly as day7 does. No model calls."""
    use_rerank = rerank.available()
    hits = retrieval.retrieve([question], settings.corpus_owner,
                              k=settings.rerank_candidates - 2 if use_rerank else None,
                              min_score=0.0 if use_rerank else None)
    info = {"candidates": len(hits), "scorer": None, "best_relevance": None, "zone": None, "notes": []}
    if not hits:
        info["zone"] = "low"
        return {**info, "passages": []}
    ranked = _rerank_with_patience(question, hits) if use_rerank else None
    if ranked is None:
        # No reranker: keep the fused search order (day7 would ask an LLM to grade; that would add a model).
        info["notes"].append("reranker unavailable: passages kept in search order")
        chosen = hits[: settings.retrieval_k]
        return {**info, "zone": "unscored", "passages": chosen}
    best = ranked[0]["relevance"]
    zone = rerank.zone(best, ranked[0].get("scorer"))
    info.update(scorer=ranked[0].get("scorer"), best_relevance=best, zone=zone)
    chosen = rerank.mmr_select(ranked) if zone != "low" else []
    return {**info, "passages": chosen}


def answer(question: str, model_key: str) -> dict:
    """Answer one question. Raises models.RateLimited when the base model's quota is used up."""
    started = time.perf_counter()
    found = retrieve_passages(question)
    passages = found["passages"]
    record = {
        "retrieval": {k: v for k, v in found.items() if k != "passages"},
        "passages": [{"n": i, "source": p["source"], "page": p.get("page"), "chunk_index": p.get("chunk_index"),
                      "relevance": p.get("relevance"), "content": p["content"]}
                     for i, p in enumerate(passages, start=1)],
    }
    if not passages:
        return {**record, "answer": NOT_COVERED, "answered_from_documents": False, "model": None,
                "usage": None, "citations": None, "latency_s": round(time.perf_counter() - started, 2)}

    prompt = f"Document excerpts:\n\n{format_context(passages)}\n\n---\nQuestion: {question}"
    result = models.chat(model_key, SYSTEM, prompt, max_tokens=settings.answer_max_output_tokens)
    text = _clean(result.text)
    # day7: the sentinel means "nothing at all" only when it IS the reply.
    without = text.replace(NO_ANSWER, "").strip(" \n.:-—")
    answered = len(without) >= 40
    if not answered:
        text = NOT_COVERED
    elif NO_ANSWER in text:
        text = text.replace(NO_ANSWER, "The documents don't cover the rest of this question.").strip()

    report = citations.check(text, [p["content"] for p in passages], question=question) if answered else None
    return {
        **record,
        "answer": text,
        "answered_from_documents": answered,
        "model": {"key": result.model_key, "id": result.model_id, "notes": result.notes},
        "usage": {"input": result.input_tokens, "output": result.output_tokens,
                  "reasoning": result.reasoning_tokens, "model_latency_s": result.latency_s},
        "citations": None if report is None else {
            "ok": report.ok, "claims": report.sentences, "uncited": len(report.uncited),
            "invalid": sorted(set(report.invalid)), "unsupported": len(report.unsupported),
            "support": report.support, "problems": report.problems,
        },
        "latency_s": round(time.perf_counter() - started, 2),
    }
