"""Runs a case: three lanes in parallel threads.

    base   answers every question (base_agent)            -> generated.json, shared by every case
    small  grades each answer as soon as it exists       -> judge_small.json
    large  same, with the larger judge                   -> judge_large.json

Every lane saves after each question and skips work that is already done, so a stopped or crashed run
resumes where it left off. A result is redone when its inputs change (question, rubric, or the answer a
judge graded). On a rate limit a lane waits as long as the provider asks (until the daily reset, if that
is what ran out); the other lanes keep going, since every model has its own quota.
"""
import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from validator import base_agent, judge, models, store
from validator.config import CASES, MODELS

log = logging.getLogger(__name__)

_answer_lock = threading.Lock()  # one base lane answers at a time: see Run._base_lane


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Lane:
    def __init__(self, name: str, model_key: str, total: int):
        self.name, self.model_key, self.total = name, model_key, total
        self.state = "idle"          # idle | running | waiting | done | stopped | error
        self.done = 0
        self.errors = 0
        self.current: str | None = None
        self.wait_until: str | None = None
        self.message = ""

    def view(self) -> dict:
        return {"name": self.name, "model": self.model_key, "label": MODELS[self.model_key].label,
                "state": self.state, "done": self.done, "total": self.total, "errors": self.errors,
                "current": self.current, "wait_until": self.wait_until, "message": self.message}


class Run:
    def __init__(self, case_key: str, limit: int | None = None):
        self.case = CASES[case_key]
        self.limit = limit
        self.stop_event = threading.Event()
        self.log: deque[str] = deque(maxlen=300)
        self.started_at = _now()
        self.questions = store.questions()[:limit] if limit else store.questions()
        self.expected = store.expected()
        n = len(self.questions)
        self.lanes = {"base": Lane("base", self.case.base, n),
                      "small": Lane("small", self.case.small_judge, n),
                      "large": Lane("large", self.case.large_judge, n)}
        self.threads: list[threading.Thread] = []

    # ------------------------------------------------------------ helpers
    def say(self, msg: str) -> None:
        line = f"{datetime.now().strftime('%H:%M:%S')}  {msg}"
        self.log.append(line)
        log.info("[%s] %s", self.case.key, msg)

    def _sleep(self, seconds: float) -> bool:
        """Sleep unless stopped. Returns False if the run was stopped."""
        return not self.stop_event.wait(seconds)

    def _wait_out(self, lane: Lane, e: models.RateLimited) -> bool:
        until = datetime.now(timezone.utc) + timedelta(seconds=e.wait_seconds)
        lane.state, lane.wait_until = "waiting", until.isoformat(timespec="seconds")
        kind = "daily quota used up" if e.daily else "rate limit"
        lane.message = f"{MODELS[e.model].label}: {kind}, waiting {int(e.wait_seconds)}s"
        self.say(f"{lane.name}: {lane.message}")
        ok = self._sleep(e.wait_seconds)
        lane.state, lane.wait_until, lane.message = "running", None, ""
        return ok

    def _question_key(self, q: dict) -> str:
        # The prompt and the base model are part of the key: changing either redoes the answers.
        return store.fingerprint(q["question"], base_agent.SYSTEM, self.case.base)

    # ------------------------------------------------------------ lanes
    def _base_lane(self) -> None:
        lane = self.lanes["base"]
        lane.state = "running"
        for q in self.questions:
            # The answers are shared by every case. If both cases run at once, their base lanes take turns
            # question by question; the second finds the answer already saved, so each is answered once.
            while not self.stop_event.is_set() and not _answer_lock.acquire(timeout=1):
                lane.current, lane.message = None, "the other case is answering"
            if self.stop_event.is_set():
                break
            try:
                lane.message = ""
                self._answer(lane, q)
            finally:
                _answer_lock.release()
        lane.current = None
        lane.state = "stopped" if self.stop_event.is_set() else "done"

    def _answer(self, lane: Lane, q: dict) -> None:
        done = store.load(self.case.key, "generated").get(q["id"])
        if done and not done.get("error") and done.get("question_key") == self._question_key(q):
            lane.done += 1
            return
        lane.current = q["id"]
        while not self.stop_event.is_set():
            try:
                record = base_agent.answer(q["question"], self.case.base)
                store.save_item(self.case.key, "generated", q["id"], {
                    "id": q["id"], "question": q["question"], "question_key": self._question_key(q),
                    "at": _now(), **record})
                lane.done += 1
                zone = record["retrieval"].get("zone")
                self.say(f"base: {q['id']} answered ({zone} match, {record['latency_s']}s)")
                break
            except models.RateLimited as e:
                if not self._wait_out(lane, e):
                    break
            except Exception as e:  # noqa: BLE001 - recorded; the next run retries it
                lane.errors += 1
                store.save_item(self.case.key, "generated", q["id"], {
                    "id": q["id"], "question": q["question"], "question_key": self._question_key(q),
                    "at": _now(), "error": f"{type(e).__name__}: {str(e)[:500]}"})
                self.say(f"base: {q['id']} failed: {type(e).__name__}: {str(e)[:200]}")
                break

    def _judge_lane(self, which: str) -> None:
        lane = self.lanes[which]
        model_key = self.case.judges[which]
        name = f"judge_{which}"
        lane.state = "running"
        failed: set[str] = set()   # failed in this run: retried on the next run, not in a loop now
        while not self.stop_event.is_set():
            generated = store.load(self.case.key, "generated")
            results = store.load(self.case.key, name)
            pending, finished = [], 0
            for q in self.questions:
                g = generated.get(q["id"])
                if not g or g.get("error") or g.get("question_key") != self._question_key(q):
                    continue
                key = store.fingerprint(q["question"], self.expected.get(q["id"]), g["answer"],
                                        judge.PLAN_SYSTEM, judge.GRADE_SYSTEM)
                r = results.get(q["id"])
                if r and not r.get("error") and r.get("input_key") == key:
                    finished += 1
                elif q["id"] not in failed:
                    pending.append((q, g, key))
            lane.done = finished
            if not pending:
                if self.lanes["base"].state in ("done", "stopped", "error"):
                    break
                lane.current, lane.message = None, "waiting for answers"
                if not self._sleep(5):
                    break
                continue
            lane.message = ""
            q, g, key = pending[0]
            lane.current = q["id"]
            try:
                verdict = judge.judge(model_key, q, self.expected[q["id"]], g)
                store.save_item(self.case.key, name, q["id"], {
                    "id": q["id"], "input_key": key, "judge": model_key, "at": _now(), **verdict})
                self.say(f"{which}: {q['id']} -> {verdict['verdict']} ({verdict['latency_s']}s)")
            except models.RateLimited as e:
                if not self._wait_out(lane, e):
                    break
            except Exception as e:  # noqa: BLE001 - recorded; the next run retries it
                lane.errors += 1
                failed.add(q["id"])
                store.save_item(self.case.key, name, q["id"], {
                    "id": q["id"], "input_key": key, "judge": model_key, "at": _now(),
                    "error": f"{type(e).__name__}: {str(e)[:500]}"})
                self.say(f"{which}: {q['id']} failed: {type(e).__name__}: {str(e)[:200]}")
        lane.current = None
        lane.state = "stopped" if self.stop_event.is_set() else "done"

    # ------------------------------------------------------------ control
    def start(self) -> None:
        self.say(f"Started {self.case.label} on {len(self.questions)} questions")
        targets = [("base", self._base_lane), ("small", lambda: self._judge_lane("small")),
                   ("large", lambda: self._judge_lane("large"))]
        for name, target in targets:
            t = threading.Thread(target=self._guard(name, target), name=f"{self.case.key}-{name}", daemon=True)
            self.threads.append(t)
            t.start()

    def _guard(self, name: str, target):
        def run():
            try:
                target()
            except Exception as e:  # noqa: BLE001 - a lane crash must not take the server down
                self.lanes[name].state = "error"
                self.lanes[name].message = f"{type(e).__name__}: {str(e)[:300]}"
                self.say(f"{name}: crashed: {self.lanes[name].message}")
                log.exception("Lane %s crashed", name)
        return run

    def stop(self) -> None:
        self.stop_event.set()
        self.say("Stop requested")

    @property
    def active(self) -> bool:
        return any(t.is_alive() for t in self.threads)

    def wait(self) -> None:
        for t in self.threads:
            while t.is_alive():
                t.join(timeout=1)

    def view(self) -> dict:
        return {"case": self.case.key, "active": self.active, "started_at": self.started_at, "limit": self.limit,
                "lanes": {k: v.view() for k, v in self.lanes.items()}, "log": list(self.log)[-80:]}


# ---------------------------------------------------------------- one run per case at a time
_runs: dict[str, Run] = {}
_runs_lock = threading.Lock()


def start(case_key: str, limit: int | None = None) -> Run:
    with _runs_lock:
        current = _runs.get(case_key)
        if current and current.active:
            raise RuntimeError(f"{case_key} is already running")
        problems = store.validate_question_set()
        if problems:
            raise RuntimeError("The question set has problems: " + "; ".join(problems[:5]))
        run = Run(case_key, limit)
        _runs[case_key] = run
        run.start()
        return run


def get(case_key: str) -> Run | None:
    return _runs.get(case_key)


def stop(case_key: str) -> None:
    run = _runs.get(case_key)
    if run:
        run.stop()


def stop_all() -> None:
    for run in _runs.values():
        run.stop()
