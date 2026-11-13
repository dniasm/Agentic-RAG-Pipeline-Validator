"""The runner with fake models: lanes, resume, rate-limit waits and recorded failures."""
import json

import pytest

from validator import base_agent, judge, models, runner, store
from validator.config import settings


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    qs = [{"id": f"Q{i}", "question": f"question {i}"} for i in range(1, 4)]
    ex = [{"id": q["id"], "answerable": True, "must_include": ["x"]} for q in qs]
    (tmp_path / "q.json").write_text(json.dumps(qs))
    (tmp_path / "e.json").write_text(json.dumps(ex))
    monkeypatch.setattr(settings, "questions_path", str(tmp_path / "q.json"))
    monkeypatch.setattr(settings, "expected_path", str(tmp_path / "e.json"))
    monkeypatch.setattr(settings, "runs_dir", str(tmp_path / "runs"))
    calls = {"answer": [], "judge": []}

    def fake_answer(question, model_key):
        calls["answer"].append(question)
        return {"retrieval": {"zone": "high"}, "passages": [], "answer": f"answer to {question}",
                "answered_from_documents": True, "model": None, "usage": None, "citations": None, "latency_s": 0}

    def fake_judge(model_key, q, e, g):
        calls["judge"].append((model_key, q["id"]))
        return {"verdict": "pass", "score": 9, "rubric": [], "queries": [], "passages": [], "latency_s": 0,
                "calls": [], "grounding": "supported", "confidence": "high", "reason": "ok"}

    monkeypatch.setattr(base_agent, "answer", fake_answer)
    monkeypatch.setattr(judge, "judge", fake_judge)
    monkeypatch.setattr(runner.Run, "_sleep", lambda self, s: not self.stop_event.is_set())
    return calls


def _run(case="case2"):
    run = runner.start(case)
    run.wait()
    return run


def test_all_lanes_finish(workspace):
    run = _run()
    assert {k: (v.state, v.done) for k, v in run.lanes.items()} == {
        "base": ("done", 3), "small": ("done", 3), "large": ("done", 3)}
    assert len(store.load("case2", "judge_large")) == 3


def test_resume_skips_finished_work(workspace):
    _run()
    workspace["answer"].clear()
    workspace["judge"].clear()
    _run()
    assert workspace == {"answer": [], "judge": []}


def test_changed_rubric_regrades_only_that_question(workspace):
    _run()
    workspace["judge"].clear()
    ex = json.loads(open(settings.expected_path).read())
    ex[1]["must_include"] = ["y"]
    open(settings.expected_path, "w").write(json.dumps(ex))
    _run()
    assert sorted(workspace["judge"]) == [("gpt-oss-20b", "Q2"), ("nemotron-super", "Q2")]


def test_rate_limit_is_waited_out(workspace, monkeypatch):
    real = judge.judge
    hits = {"n": 0}

    def limited(model_key, q, e, g):
        if model_key == "nemotron-super" and hits["n"] == 0:
            hits["n"] += 1
            raise models.RateLimited(model_key, 5, False, "slow down")
        return real(model_key, q, e, g)

    monkeypatch.setattr(judge, "judge", limited)
    run = _run()
    assert run.lanes["large"].done == 3 and run.lanes["large"].errors == 0
    assert any("rate limit" in line for line in run.log)


def test_failure_is_recorded_and_retried_next_run(workspace, monkeypatch):
    real = base_agent.answer

    def broken(question, model_key):
        if question == "question 2":
            raise ValueError("boom")
        return real(question, model_key)

    monkeypatch.setattr(base_agent, "answer", broken)
    run = _run()
    assert run.lanes["base"].errors == 1
    assert "boom" in store.load("case2", "generated")["Q2"]["error"]
    assert "Q2" not in store.load("case2", "judge_small")  # nothing to grade for a failed answer

    monkeypatch.setattr(base_agent, "answer", real)
    _run()
    assert "error" not in store.load("case2", "generated")["Q2"]
    assert store.load("case2", "judge_small")["Q2"]["verdict"] == "pass"


def test_second_case_reuses_the_shared_answers(workspace):
    _run("case2")
    workspace["answer"].clear()
    workspace["judge"].clear()
    _run("case1")
    assert workspace["answer"] == []  # nothing answered again
    assert sorted({m for m, _ in workspace["judge"]}) == ["gemma-4-31b", "nemotron-ultra"]
    assert store.load("case1", "generated") == store.load("case2", "generated")


def test_both_cases_at_once_answer_each_question_once(workspace):
    a, b = runner.start("case2"), runner.start("case1")
    a.wait()
    b.wait()
    assert sorted(workspace["answer"]) == ["question 1", "question 2", "question 3"]
    assert len(store.load("case1", "judge_small")) == len(store.load("case2", "judge_small")) == 3


def test_base_agent_gets_only_the_question_text(workspace, monkeypatch):
    seen = []

    def spy(*args, **kwargs):
        seen.append((args, kwargs))
        return {"retrieval": {"zone": "high"}, "passages": [], "answer": "a", "answered_from_documents": True,
                "model": None, "usage": None, "citations": None, "latency_s": 0}

    monkeypatch.setattr(base_agent, "answer", spy)
    _run()
    assert seen and all(kw == {} and args[0].startswith("question ") and args[1] == "gpt-oss-120b"
                        for args, kw in seen)


def test_base_agent_cannot_reach_the_answer_key():
    import inspect
    src = inspect.getsource(base_agent)
    assert "store" not in src and "expected" not in src


def test_answer_key_inside_corpus_is_refused(workspace, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "corpus_dir", str(tmp_path))
    assert not store.answer_key_is_isolated()
    assert any("corpus folder" in p for p in store.validate_question_set())
