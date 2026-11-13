"""Files: the question set, the expected-answer rubric, and each case's results.

data/questions.json            [{"id", "question", "type"}]
data/expected.json             [{"id", "answerable", "must_include", "should_include", "must_not_include", "notes"?,
                                 "source_files"?}]  the answer key: only the judges and the metrics read it,
                                 never the base agent, and it must stay outside the corpus folder
data/runs/generated.json             the base agent's answers, by question id: ONE file shared by every case,
                                     so all four judges grade exactly the same answers
data/runs/<case>/judge_small.json    the smaller judge's results, by question id
data/runs/<case>/judge_large.json    the larger judge's results, by question id
data/runs/<case>/human.json          the human checker's verdicts, by question id
data/runs/<case>/metrics.json        the latest computed metrics
"""
import hashlib
import json
import os
import threading
import time
from pathlib import Path

from validator.config import settings

_lock = threading.Lock()


def _read(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    """Write atomically, so a crash mid-write never leaves a half-written results file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    # Windows refuses to replace a file another process has open (an editor, antivirus, the portal reading it):
    # retry briefly instead of failing the lane.
    for attempt in range(10):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.05 * (attempt + 1))


def fingerprint(*parts) -> str:
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- question set
def questions() -> list[dict]:
    return _read(Path(settings.questions_path), [])


def expected() -> dict[str, dict]:
    return {e["id"]: e for e in _read(Path(settings.expected_path), [])}


def answer_key_is_isolated() -> bool:
    """The expected answers must never be ingested: anything in the corpus folder is searchable by the base agent."""
    corpus = Path(settings.corpus_dir).resolve()
    return all(corpus not in Path(p).resolve().parents for p in (settings.expected_path, settings.questions_path))


def validate_question_set() -> list[str]:
    """Problems with the question set (empty list = fine)."""
    problems = []
    if not answer_key_is_isolated():
        problems.append("The question set or expected answers are inside the corpus folder, where the base agent "
                        "could retrieve them: move them out")
    qs, ex = questions(), expected()
    ids = [q.get("id") for q in qs]
    if not qs:
        problems.append(f"No questions found in {settings.questions_path}")
    if len(ids) != len(set(ids)):
        problems.append("Duplicate question ids")
    for q in qs:
        if not q.get("question"):
            problems.append(f"{q.get('id')}: empty question")
        e = ex.get(q.get("id"))
        if not e:
            problems.append(f"{q.get('id')}: no expected-answer rubric")
        elif not e.get("must_include"):
            problems.append(f"{q.get('id')}: rubric has no must_include points")
    for extra in set(ex) - set(ids):
        problems.append(f"{extra}: rubric without a question")
    return problems


# ---------------------------------------------------------------- results
SHARED = {"generated"}  # the same in every case: both cases use the same base model


def run_dir(case: str) -> Path:
    return Path(settings.runs_dir) / case


def _path(case: str, name: str) -> Path:
    if name in SHARED:
        return Path(settings.runs_dir) / f"{name}.json"
    return run_dir(case) / f"{name}.json"


def load(case: str, name: str) -> dict:
    # Under the same lock as writes: on Windows a file that is open for reading can't be replaced.
    with _lock:
        return _read(_path(case, name), {})


def save_item(case: str, name: str, qid: str, record: dict) -> None:
    with _lock:
        path = _path(case, name)
        data = _read(path, {})
        data[qid] = record
        _write(path, data)


def save(case: str, name: str, data) -> None:
    with _lock:
        _write(_path(case, name), data)


def reset(case: str, name: str) -> None:
    with _lock:
        path = _path(case, name)
        if path.exists():
            path.unlink()
