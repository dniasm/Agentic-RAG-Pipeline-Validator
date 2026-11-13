"""Unit tests for the parts that need no network or model."""
import pytest

from validator import judge, metrics, models, store
from validator.config import CASES, MODELS


# ---------------------------------------------------------------- setup rules
def test_cases_share_the_base_and_never_reuse_a_judge():
    assert {c.base for c in CASES.values()} == {"gpt-oss-120b"}
    judges = [m for c in CASES.values() for m in (c.small_judge, c.large_judge)]
    assert len(judges) == len(set(judges)) == 4
    assert "gpt-oss-120b" not in judges  # no judge grades its own model's answers


def test_every_case_model_and_fallback_is_defined():
    for c in CASES.values():
        for key in (c.base, c.small_judge, c.large_judge):
            assert key in MODELS
            if MODELS[key].fallback:
                assert MODELS[key].fallback in MODELS


def test_case2_runs_first():
    assert min(CASES.values(), key=lambda c: c.order).key == "case2"


# ---------------------------------------------------------------- kappa
def test_kappa_perfect_agreement():
    a = ["pass", "fail", "partial", "pass"]
    assert metrics.cohen_kappa(a, a) == 1.0


def test_kappa_known_value():
    # 2x2 classic example within 3 labels: observed 0.7, expected 0.5 -> kappa 0.4
    a = ["pass"] * 5 + ["fail"] * 5
    b = ["pass"] * 4 + ["fail"] + ["pass"] * 2 + ["fail"] * 3
    assert metrics.cohen_kappa(a, b) == pytest.approx(0.4, abs=1e-3)


def test_weighted_kappa_penalises_far_disagreements_more():
    a = ["pass", "pass", "fail", "partial", "fail", "pass"]
    near = ["partial", "pass", "fail", "partial", "partial", "pass"]
    far = ["fail", "pass", "pass", "partial", "pass", "pass"]
    assert metrics.cohen_kappa(a, near, weighted=True) > metrics.cohen_kappa(a, far, weighted=True)


def test_kappa_empty():
    assert metrics.cohen_kappa([], []) is None


# ---------------------------------------------------------------- rubric and verdict rules
EXPECTED = {"id": "Q1", "answerable": True, "must_include": ["a", "b"], "should_include": ["c"],
            "must_not_include": ["d"]}


def test_rubric_points_are_numbered_by_kind():
    ids = [(p["id"], p["kind"]) for p in judge.rubric_points(EXPECTED)]
    assert ids == [("M1", "must_include"), ("M2", "must_include"), ("S1", "should_include"),
                   ("N1", "must_not_include")]


def _result(*statuses, contradicted=None):
    kinds = ["must_include", "must_include", "should_include", "must_not_include"]
    return {"rubric": [{"id": str(i), "kind": k, "status": s} for i, (k, s) in enumerate(zip(kinds, statuses))],
            "contradicted_by_corpus": contradicted or []}


@pytest.mark.parametrize("statuses,expected", [
    (("covered", "covered", "missing", "respected"), "pass"),
    (("covered", "partial", "covered", "respected"), "partial"),
    (("missing", "missing", "covered", "respected"), "fail"),
    (("covered", "covered", "covered", "violated"), "fail"),
])
def test_rule_verdict(statuses, expected):
    assert metrics.rule_verdict(_result(*statuses)) == expected


def test_rule_verdict_contradiction_fails():
    assert metrics.rule_verdict(_result("covered", "covered", "covered", "respected", contradicted=["x"])) == "fail"


def test_coverage_counts_partial_as_half():
    assert metrics.coverage(_result("covered", "partial", "missing", "respected"), "must_include") == 0.75


# ---------------------------------------------------------------- judge reply parsing
def test_json_object_from_fenced_reply():
    reply = 'Sure.\n```json\n{"queries": ["bm25 k1", "saturation"]}\n```'
    assert judge.Plan.model_validate(judge._json_object(reply)).queries == ["bm25 k1", "saturation"]


def test_grade_schema_rejects_bad_verdict():
    with pytest.raises(Exception):
        judge.Grade.model_validate({"rubric": [], "grounding": "supported", "verdict": "great", "score": 5,
                                    "confidence": "high", "reason": "x"})


# ---------------------------------------------------------------- rate-limit parsing
@pytest.mark.parametrize("message,seconds", [
    ("Rate limit reached ... Please try again in 7m12.5s.", 432.5),
    ("429 RESOURCE_EXHAUSTED ... Please retry in 31.2s.", 31.2),
    ("Please try again in 1h2m3s", 3723),
    ("Please try again in 950ms", None),  # sub-second waits fall back to the default
])
def test_parse_wait(message, seconds):
    assert models._parse_wait(message) == (pytest.approx(seconds) if seconds else None)


def test_classify_daily_limit():
    class E(Exception):
        status_code = 429
    err = models._classify(MODELS["gpt-oss-20b"],
                           E("Rate limit reached on tokens per day (TPD): Limit 200000. Please try again in 1h2m3s"))
    assert isinstance(err, models.RateLimited) and err.daily and err.wait_seconds == pytest.approx(3725)


def test_classify_retired_model():
    class E(Exception):
        status_code = 410
    assert isinstance(models._classify(MODELS["step-5"], E("has reached its end of life")), models.ModelUnavailable)


def test_text_of_drops_think_blocks_and_joins_parts():
    assert models._text_of("<think>hmm</think> Answer") == "Answer"
    assert models._text_of([{"type": "thinking", "thinking": "x"}, {"type": "text", "text": "Hi"}]) == "Hi"


# ---------------------------------------------------------------- base agent clean-up
def test_gpt_oss_citations_are_normalised():
    from validator import base_agent
    assert base_agent._clean("BM25 saturates【1†L3-L5】 and【2】.") == "BM25 saturates[1] and[2]."


# ---------------------------------------------------------------- store
def test_fingerprint_changes_with_content():
    assert store.fingerprint("q", {"a": 1}) == store.fingerprint("q", {"a": 1})
    assert store.fingerprint("q", {"a": 1}) != store.fingerprint("q", {"a": 2})


# ---------------------------------------------------------------- ingestion batching
def test_embedding_batches_respect_count_and_token_caps():
    from validator.rag import ingestion
    small = ["word " * 20] * 200                      # 100 chars each: the count cap (90) applies
    assert [len(b) for _, b in ingestion.batches(small)] == [90, 90, 20]
    dense = ["1,234.5 " * 125] * 90                    # 1,000 chars each (~1,000 tokens for a table): token cap
    sizes = [len(b) for _, b in ingestion.batches(dense)]
    assert sum(sizes) == 90 and all(n * 1001 <= ingestion.EMBED_BATCH_TOKENS for n in sizes)
    starts = [s for s, _ in ingestion.batches(dense)]
    assert starts == [sum(sizes[:i]) for i in range(len(sizes))]


def test_embedding_pacing_waits_for_the_minute_to_clear():
    from validator.rag import ingestion
    ingestion._sent.clear()
    t = {"now": 1000.0}
    slept = []

    def sleep(s):
        slept.append(s)
        t["now"] += s

    ingestion._sent.append((t["now"], 20_000, 20))
    ingestion._wait_for_room(10_000, 20, sleep=sleep, clock=lambda: t["now"])  # 30K > 25K budget: must wait
    assert slept and sum(slept) >= 61
    slept.clear()
    ingestion._wait_for_room(10_000, 20, sleep=sleep, clock=lambda: t["now"])  # window cleared: no wait
    assert not slept
    ingestion._sent.clear()
