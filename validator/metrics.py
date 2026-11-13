"""Evaluation metrics for a case: the base agent, each judge, how the judges agree, and how they compare with
the human checker.

Verdicts are ordinal: fail < partial < pass. Rubric coverage counts "covered" as 1 and "partial" as 0.5.
Cohen's kappa measures agreement beyond chance (1 = perfect, 0 = no better than chance); the weighted version
counts pass-vs-partial as a smaller disagreement than pass-vs-fail.
"""
import csv
import io
import math
from collections import Counter
from statistics import mean, median

from validator import store
from validator.config import CASES, MODELS

VERDICTS = ["fail", "partial", "pass"]
_POINT = {"covered": 1.0, "partial": 0.5, "missing": 0.0}


# ---------------------------------------------------------------- statistics helpers
def _rate(n: int, d: int) -> float | None:
    return round(n / d, 3) if d else None


def _avg(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(mean(values), 3) if values else None


def _med(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(median(values), 3) if values else None


def cohen_kappa(a: list[str], b: list[str], weighted: bool = False) -> float | None:
    """Cohen's kappa for two raters over the ordinal labels fail/partial/pass."""
    if len(a) != len(b) or not a:
        return None
    k, n = len(VERDICTS), len(a)
    idx = {v: i for i, v in enumerate(VERDICTS)}
    weight = (lambda i, j: abs(i - j) / (k - 1)) if weighted else (lambda i, j: 0.0 if i == j else 1.0)
    observed = [[0] * k for _ in range(k)]
    for x, y in zip(a, b):
        observed[idx[x]][idx[y]] += 1
    row = [sum(observed[i]) for i in range(k)]
    col = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    disagree_obs = sum(weight(i, j) * observed[i][j] for i in range(k) for j in range(k)) / n
    disagree_exp = sum(weight(i, j) * row[i] * col[j] for i in range(k) for j in range(k)) / (n * n)
    if disagree_exp == 0:
        return 1.0 if disagree_obs == 0 else None
    return round(1 - disagree_obs / disagree_exp, 3)


def pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None
    mx, my = mean(x), mean(y)
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if not sx or not sy:
        return None
    return round(sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy), 3)


def confusion(a: list[str], b: list[str]) -> dict:
    """counts[row label][column label]"""
    table = {r: {c: 0 for c in VERDICTS} for r in VERDICTS}
    for x, y in zip(a, b):
        table[x][y] += 1
    return table


# ---------------------------------------------------------------- per-question derived values
def coverage(result: dict, kind: str) -> float | None:
    points = [p for p in result.get("rubric", []) if p.get("kind") == kind]
    if not points:
        return None
    return sum(_POINT.get(p["status"], 0.0) for p in points) / len(points)


def rule_verdict(result: dict) -> str:
    """The verdict the grading rules imply from the judge's own rubric grades (checks judge consistency)."""
    must = [p["status"] for p in result.get("rubric", []) if p.get("kind") == "must_include"]
    violated = any(p["status"] == "violated" for p in result.get("rubric", []))
    if violated or result.get("contradicted_by_corpus"):
        return "fail"
    if must and all(s == "covered" for s in must):
        return "pass"
    if must and sum(_POINT.get(s, 0) for s in must) / len(must) >= 0.5:
        return "partial"
    return "fail"


def _tokens(calls: list[dict]) -> int:
    return sum((c.get("input") or 0) + (c.get("output") or 0) for c in calls or [])


# ---------------------------------------------------------------- sections
def _base_metrics(questions, expected, generated) -> dict:
    rows = [generated.get(q["id"]) for q in questions]
    ok = [r for r in rows if r and not r.get("error")]
    answerable = [q for q in questions if expected.get(q["id"], {}).get("answerable", True)]
    unanswerable = [q for q in questions if not expected.get(q["id"], {}).get("answerable", True)]

    def answered(q):
        r = generated.get(q["id"])
        return bool(r and not r.get("error") and r.get("answered_from_documents"))

    def source_files(q):
        # Part of the answer key (expected.json); older question sets kept them on the question.
        return expected.get(q["id"], {}).get("source_files") or q.get("source_files") or []

    with_source = [q for q in questions if source_files(q) and generated.get(q["id"], {}).get("passages")
                   is not None and not generated.get(q["id"], {}).get("error")]

    def hit(q):
        sources = {p["source"] for p in generated[q["id"]].get("passages", [])}
        return bool(sources & set(source_files(q)))

    def first_rank(q):
        for p in generated[q["id"]].get("passages", []):
            if p["source"] in source_files(q):
                return p["n"]
        return None

    cites = [r["citations"] for r in ok if r.get("citations")]
    usage = [r["usage"] for r in ok if r.get("usage")]
    return {
        "answered": len(ok),
        "errors": sum(1 for r in rows if r and r.get("error")),
        "answered_from_documents": _rate(sum(1 for r in ok if r.get("answered_from_documents")), len(ok)),
        "answerable_answered": _rate(sum(answered(q) for q in answerable), len(answerable)),
        "unanswerable_declined": _rate(sum(not answered(q) for q in unanswerable if generated.get(q["id"])),
                                       sum(1 for q in unanswerable if generated.get(q["id"]))),
        "match_zones": dict(Counter(r["retrieval"].get("zone") for r in ok)),
        "mean_best_relevance": _avg(r["retrieval"].get("best_relevance") for r in ok),
        # Retrieval against the source files named in the question set (only questions that name one).
        "source_hit_rate": _rate(sum(hit(q) for q in with_source), len(with_source)),
        "source_mrr": _avg([(1 / first_rank(q)) if first_rank(q) else 0.0 for q in with_source]) if with_source else None,
        "citations_ok": _rate(sum(1 for c in cites if c["ok"]), len(cites)),
        "mean_citation_support": _avg(c["support"] for c in cites),
        "latency_s": {"mean": _avg(r.get("latency_s") for r in ok), "median": _med(r.get("latency_s") for r in ok)},
        "tokens": {"input": sum(u["input"] for u in usage), "output": sum(u["output"] for u in usage),
                   "reasoning": sum(u["reasoning"] for u in usage)},
        "fallback_used": sum(1 for r in ok if (r.get("model") or {}).get("notes")),
    }


def _judge_metrics(questions, results) -> dict:
    rows = [results.get(q["id"]) for q in questions]
    ok = [r for r in rows if r and not r.get("error")]
    verdicts = Counter(r["verdict"] for r in ok)
    by_type: dict[str, Counter] = {}
    for q in questions:
        r = results.get(q["id"])
        if r and not r.get("error"):
            by_type.setdefault(q.get("type", "untyped"), Counter())[r["verdict"]] += 1
    return {
        "graded": len(ok),
        "errors": sum(1 for r in rows if r and r.get("error")),
        "verdicts": {v: verdicts.get(v, 0) for v in VERDICTS},
        "pass_rate": _rate(verdicts.get("pass", 0), len(ok)),
        "pass_or_partial_rate": _rate(verdicts.get("pass", 0) + verdicts.get("partial", 0), len(ok)),
        "mean_score": _avg(r["score"] for r in ok),
        "must_coverage": _avg(coverage(r, "must_include") for r in ok),
        "should_coverage": _avg(coverage(r, "should_include") for r in ok),
        "must_not_violations": sum(1 for r in ok for p in r.get("rubric", []) if p["status"] == "violated"),
        "grounding": dict(Counter(r["grounding"] for r in ok)),
        "unsupported_claims": sum(len(r.get("unsupported_claims") or []) for r in ok),
        "contradicted_claims": sum(len(r.get("contradicted_by_corpus") or []) for r in ok),
        "confidence": dict(Counter(r["confidence"] for r in ok)),
        # How often the judge's verdict matches what its own rubric grades imply.
        "self_consistency": _rate(sum(1 for r in ok if rule_verdict(r) == r["verdict"]), len(ok)),
        "ungraded_rubric_points": sum(len(r.get("ungraded_points") or []) for r in ok),
        "pass_rate_by_type": {t: _rate(c.get("pass", 0), sum(c.values())) for t, c in sorted(by_type.items())},
        "latency_s": {"mean": _avg(r.get("latency_s") for r in ok), "median": _med(r.get("latency_s") for r in ok)},
        "tokens": sum(_tokens(r.get("calls")) for r in ok),
        "calls": sum(len(r.get("calls") or []) for r in ok),
        "fallback_used": sum(1 for r in ok if any(c.get("model") != r.get("judge") for c in r.get("calls") or [])),
    }


def _agreement(questions, a: dict, b: dict, label_a: str, label_b: str) -> dict:
    pairs = [(a[q["id"]], b[q["id"]]) for q in questions
             if q["id"] in a and q["id"] in b and not a[q["id"]].get("error") and not b[q["id"]].get("error")]
    va, vb = [x["verdict"] for x, _ in pairs], [y["verdict"] for _, y in pairs]
    point_pairs = []
    for x, y in pairs:
        ys = {p["id"]: p["status"] for p in y.get("rubric", [])}
        point_pairs += [(p["status"], ys[p["id"]]) for p in x.get("rubric", []) if p["id"] in ys]
    scores = [(x["score"], y["score"]) for x, y in pairs]
    return {
        "between": [label_a, label_b],
        "compared": len(pairs),
        "verdict_agreement": _rate(sum(1 for x, y in zip(va, vb) if x == y), len(pairs)),
        "cohen_kappa": cohen_kappa(va, vb),
        "weighted_kappa": cohen_kappa(va, vb, weighted=True),
        "rubric_point_agreement": _rate(sum(1 for x, y in point_pairs if x == y), len(point_pairs)),
        "score_correlation": pearson([s for s, _ in scores], [t for _, t in scores]),
        "mean_score_difference": _avg(abs(s - t) for s, t in scores),
        "confusion": confusion(va, vb) if pairs else None,
        "disagreements": [{"id": q["id"], label_a: a[q["id"]]["verdict"], label_b: b[q["id"]]["verdict"]}
                          for q in questions if q["id"] in a and q["id"] in b
                          and not a[q["id"]].get("error") and not b[q["id"]].get("error")
                          and a[q["id"]]["verdict"] != b[q["id"]]["verdict"]],
    }


def _human_as_results(human: dict) -> dict:
    return {qid: {"verdict": h["verdict"], "score": h.get("score", {"pass": 9, "partial": 5, "fail": 1}[h["verdict"]]),
                  "rubric": []} for qid, h in human.items() if h.get("verdict") in VERDICTS}


def compute(case_key: str) -> dict:
    case = CASES[case_key]
    questions, expected = store.questions(), store.expected()
    generated = store.load(case_key, "generated")
    small, large = store.load(case_key, "judge_small"), store.load(case_key, "judge_large")
    human = store.load(case_key, "human")
    small_label, large_label = MODELS[case.small_judge].label, MODELS[case.large_judge].label

    metrics = {
        "case": case_key,
        "label": case.label,
        "models": {"base": MODELS[case.base].label, "small_judge": small_label, "large_judge": large_label},
        "questions": len(questions),
        "base": _base_metrics(questions, expected, generated),
        "judges": {"small": _judge_metrics(questions, small), "large": _judge_metrics(questions, large)},
        "agreement": _agreement(questions, small, large, small_label, large_label),
    }
    reviewed = _human_as_results(human)
    if reviewed:
        h = Counter(r["verdict"] for r in reviewed.values())
        metrics["human"] = {
            "reviewed": len(reviewed),
            "verdicts": {v: h.get(v, 0) for v in VERDICTS},
            "pass_rate": _rate(h.get("pass", 0), len(reviewed)),
            "small_vs_human": _agreement(questions, small, reviewed, small_label, "Human"),
            "large_vs_human": _agreement(questions, large, reviewed, large_label, "Human"),
        }
    store.save(case_key, "metrics", metrics)
    return metrics


def compare_cases() -> list[dict]:
    """One summary row per case, for the side-by-side view."""
    rows = []
    for key in sorted(CASES, key=lambda k: CASES[k].order):
        m = compute(key)
        rows.append({
            "case": key, "label": m["label"], "models": m["models"],
            "answered": m["base"]["answered"], "questions": m["questions"],
            "answerable_answered": m["base"]["answerable_answered"],
            "unanswerable_declined": m["base"]["unanswerable_declined"],
            "citations_ok": m["base"]["citations_ok"],
            "small_pass_rate": m["judges"]["small"]["pass_rate"],
            "large_pass_rate": m["judges"]["large"]["pass_rate"],
            "small_must_coverage": m["judges"]["small"]["must_coverage"],
            "large_must_coverage": m["judges"]["large"]["must_coverage"],
            "judge_agreement": m["agreement"]["verdict_agreement"],
            "judge_kappa": m["agreement"]["cohen_kappa"],
            "human_pass_rate": (m.get("human") or {}).get("pass_rate"),
            "human_reviewed": (m.get("human") or {}).get("reviewed", 0),
        })
    return rows


def to_csv(case_key: str) -> str:
    """One row per question: the answer, both judges' verdicts, and the human's."""
    questions, generated = store.questions(), store.load(case_key, "generated")
    small, large = store.load(case_key, "judge_small"), store.load(case_key, "judge_large")
    human = store.load(case_key, "human")
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "type", "question", "answer", "zone", "citations_ok",
                "small_verdict", "small_score", "small_must_coverage",
                "large_verdict", "large_score", "large_must_coverage", "judges_agree", "human_verdict", "human_note"])
    for q in questions:
        g, s, l, h = (generated.get(q["id"]) or {}), (small.get(q["id"]) or {}), (large.get(q["id"]) or {}), (human.get(q["id"]) or {})
        w.writerow([q["id"], q.get("type", ""), q["question"], g.get("answer", g.get("error", "")),
                    (g.get("retrieval") or {}).get("zone", ""), (g.get("citations") or {}).get("ok", ""),
                    s.get("verdict", s.get("error", "")), s.get("score", ""), _fmt(coverage(s, "must_include")),
                    l.get("verdict", l.get("error", "")), l.get("score", ""), _fmt(coverage(l, "must_include")),
                    (s.get("verdict") == l.get("verdict")) if s.get("verdict") and l.get("verdict") else "",
                    h.get("verdict", ""), h.get("note", "")])
    return out.getvalue()


def _fmt(v):
    return "" if v is None else round(v, 2)
