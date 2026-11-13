"""A judge grades one generated answer against its rubric, using its own searches of the corpus.

Two calls per question, the same for every judge so they stay comparable:
    1. plan   the judge reads the question, rubric and answer, and writes its own search queries
    2. grade  we run those searches over the whole corpus (hybrid, no reranker); the judge grades every
              rubric point and gives a verdict
The judge never sees the passages the base agent used: its evidence comes only from its own searches.
A third call is made only if the grade reply isn't valid JSON (one repair attempt).
"""
import json
import logging
import re
import time
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from validator import corpus, models
from validator.config import settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- output formats
class Plan(BaseModel):
    queries: list[str] = Field(default_factory=list)


def _label(value):
    """"Pass" / "partly supported" / "Not-Applicable" -> "pass" / "partly_supported" / "not_applicable"."""
    return re.sub(r"[\s\-]+", "_", value.strip().lower()) if isinstance(value, str) else value


class PointGrade(BaseModel):
    id: str
    status: Literal["covered", "partial", "missing", "violated", "respected"]
    note: str = ""

    @field_validator("status", mode="before")
    @classmethod
    def _norm(cls, v):
        return _label(v)


class Grade(BaseModel):
    rubric: list[PointGrade]
    grounding: Literal["supported", "partly_supported", "unsupported", "contradicted", "not_applicable"]
    unsupported_claims: list[str] = Field(default_factory=list)
    contradicted_by_corpus: list[str] = Field(default_factory=list)
    verdict: Literal["pass", "partial", "fail"]
    score: int = Field(ge=0, le=10)
    confidence: Literal["high", "medium", "low"]
    reason: str

    @field_validator("grounding", "verdict", "confidence", mode="before")
    @classmethod
    def _norm(cls, v):
        return _label(v)


# ---------------------------------------------------------------- prompts
PLAN_SYSTEM = """You are an independent evaluator checking a question-answering system against a document corpus.
You cannot see the documents yet. Write search queries that will find the passages you need to check
(1) the claims in the generated answer and (2) the points in the grading rubric.

Rules:
- Write at most {max_queries} queries. Each is a short keyword-rich search (not a full question).
- Target different facts with different queries; don't repeat the question verbatim.
- Reply with ONLY a JSON object: {{"queries": ["...", "..."]}}"""

GRADE_SYSTEM = """You are an independent evaluator grading a generated answer from a document question-answering system.

You get: the question, a grading rubric, the generated answer, and passages from the corpus that YOUR OWN
searches found. The rubric is abstract: it lists concepts and hints the answer should contain, not exact wording.

How to grade:
- Grade every rubric point by its id:
    must_include / should_include points: "covered" (the answer conveys it), "partial" (incomplete or vague),
    or "missing".
    must_not_include points: "violated" (the answer says it) or "respected".
- Judge meaning, not wording. Any phrasing that conveys the concept counts.
- Check the answer's claims against the corpus passages. Its [n] citations point to the system's own sources,
  which you cannot see: ignore the numbers and check the claims themselves.
- "grounding": are the answer's claims supported by the corpus passages? "supported", "partly_supported",
  "unsupported", "contradicted" (the passages say otherwise), or "not_applicable" (the answer makes no factual
  claims, e.g. it says the documents don't cover it).
- List claims your passages don't support in "unsupported_claims", and claims your passages contradict in
  "contradicted_by_corpus". If your passages simply don't mention something, it is unsupported, not contradicted.
- If the rubric says the question is NOT answerable from the corpus, the right answer says the documents don't
  cover it. Inventing an answer is a fail.

Verdict (decided by must_include and must_not_include points only):
- "pass": every must_include point covered, no must_not_include point violated, nothing contradicted by the corpus.
  Missing should_include points never stop a pass: they only lower the score.
- "partial": the core of the answer is right but some must_include points are partial or missing, or it has
  unsupported (not contradicted) claims.
- "fail": most must_include points missing, any must_not_include point violated, a key claim contradicted by the
  corpus, or a wrong refusal / invented answer.
- "score": 0-10 overall quality. "confidence": how sure you are, given the evidence you found.
- "reason": 2-4 sentences explaining the verdict.

Reply with ONLY a JSON object (no prose, no code fences) in this format:
{{"rubric": [{{"id": "M1", "status": "covered", "note": "..."}}], "grounding": "supported",
 "unsupported_claims": [], "contradicted_by_corpus": [], "verdict": "pass", "score": 9,
 "confidence": "high", "reason": "..."}}"""


def rubric_points(expected: dict) -> list[dict]:
    """The rubric as numbered points: M = must include, S = should include, N = must not include."""
    points = []
    for prefix, kind, field in (("M", "must_include", "must_include"), ("S", "should_include", "should_include"),
                                ("N", "must_not_include", "must_not_include")):
        for i, text in enumerate(expected.get(field) or [], start=1):
            points.append({"id": f"{prefix}{i}", "kind": kind, "text": text})
    return points


def _rubric_text(expected: dict) -> str:
    lines = [f"Answerable from the corpus: {'yes' if expected.get('answerable', True) else 'NO'}"]
    for p in rubric_points(expected):
        lines.append(f"- {p['id']} [{p['kind']}] {p['text']}")
    if expected.get("notes"):
        lines.append(f"Grader notes: {expected['notes']}")
    return "\n".join(lines)


def _json_object(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("no JSON object in the reply")
    return json.loads(match.group(0))


def _usage(result: models.ChatResult) -> dict:
    return {"input": result.input_tokens, "output": result.output_tokens, "reasoning": result.reasoning_tokens,
            "latency_s": result.latency_s, "model": result.model_key}


# ---------------------------------------------------------------- the two steps
def plan(model_key: str, question: dict, expected: dict, generated: dict) -> tuple[list[str], dict]:
    user = (f"Question: {question['question']}\n\nGrading rubric:\n{_rubric_text(expected)}\n\n"
            f"Generated answer:\n{generated['answer']}")
    result = models.chat(model_key, PLAN_SYSTEM.format(max_queries=settings.judge_max_queries), user,
                         max_tokens=settings.judge_max_output_tokens)
    try:
        queries = Plan.model_validate(_json_object(result.text)).queries
    except (ValueError, ValidationError):
        queries = []
    queries = [q.strip() for q in queries if q and q.strip()][: settings.judge_max_queries]
    if not queries:  # unusable plan: search for the question itself rather than grade blind
        queries = [question["question"]]
    return queries, _usage(result)


def gather(queries: list[str]) -> list[dict]:
    """Run the judge's searches; keep the best few passages per query, without duplicates."""
    seen, passages = set(), []
    for q in queries:
        for hit in corpus.search(q, settings.judge_passages_per_query):
            if hit["id"] in seen:
                continue
            seen.add(hit["id"])
            passages.append({"id": hit["id"], "source": hit["source"], "page": hit.get("page"),
                             "chunk_index": hit.get("chunk_index"), "query": q,
                             "content": hit["content"][: settings.judge_passage_chars]})
    return passages[: settings.judge_max_passages]


def grade(model_key: str, question: dict, expected: dict, generated: dict, passages: list[dict]) -> tuple[Grade, list[dict]]:
    evidence = "\n\n".join(f"[S{i}] (source: {p['source']})\n{p['content']}" for i, p in enumerate(passages, 1))
    user = (f"Question: {question['question']}\n\nGrading rubric:\n{_rubric_text(expected)}\n\n"
            f"Generated answer:\n{generated['answer']}\n\n"
            f"Corpus passages from your searches:\n{evidence or '(your searches found nothing)'}")
    usages = []
    result = models.chat(model_key, GRADE_SYSTEM, user, max_tokens=settings.judge_max_output_tokens)
    usages.append(_usage(result))
    try:
        return Grade.model_validate(_json_object(result.text)), usages
    except (ValueError, ValidationError) as e:
        log.info("%s grade reply was not valid JSON (%s); asking once more", model_key, str(e)[:120])
        repair = (f"{user}\n\nYour previous reply could not be used ({str(e)[:300]}). "
                  "Reply again with ONLY the JSON object in the required format.")
        result = models.chat(model_key, GRADE_SYSTEM, repair, max_tokens=settings.judge_max_output_tokens)
        usages.append(_usage(result))
        return Grade.model_validate(_json_object(result.text)), usages


def judge(model_key: str, question: dict, expected: dict, generated: dict) -> dict:
    """Plan, search, grade. Raises models.RateLimited when the judge's quota is used up."""
    started = time.perf_counter()
    queries, plan_usage = plan(model_key, question, expected, generated)
    passages = gather(queries)
    result, grade_usage = grade(model_key, question, expected, generated, passages)
    points = {p["id"]: p for p in rubric_points(expected)}
    graded = [{**points.get(g.id, {"id": g.id, "kind": "unknown", "text": ""}), "status": g.status, "note": g.note}
              for g in result.rubric]
    missing_ids = [pid for pid in points if pid not in {g.id for g in result.rubric}]
    return {
        "queries": queries,
        "passages": passages,
        "rubric": graded,
        "ungraded_points": missing_ids,
        **result.model_dump(exclude={"rubric"}),
        "calls": [plan_usage, *grade_usage],
        "latency_s": round(time.perf_counter() - started, 2),
    }
