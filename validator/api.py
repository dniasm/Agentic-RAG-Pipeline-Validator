"""The portal's API. Run: uvicorn validator.api:app --port 8100

No login. It listens on 127.0.0.1; a shared link goes through a tunnel, and visitors arriving that way are
read-only except for human reviews (see visitors_are_read_only).
"""
import logging
import re
import shutil
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from validator import corpus, metrics, runner, store
from validator.config import CASES, MODELS, PROJECT_ROOT, quiet_noisy_loggers, settings
from validator.rag import ingestion, vectorstore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)
quiet_noisy_loggers()


@asynccontextmanager
async def lifespan(_app):
    yield
    runner.stop_all()
    vectorstore.close_client()


app = FastAPI(title="Agentic-RAG Pipeline Validator", lifespan=lifespan)

# Visitors who reach the portal through a shared link (a tunnel or another machine). With
# settings.visitors_can_run off they may only look and record human reviews: nothing that spends API quota or
# changes the corpus and results (the current choice). With it on they can do everything the host can.
_VISITOR_WRITES = re.compile(r"^/api/results/[^/]+/[^/]+/human$")


def _is_remote(request: Request) -> bool:
    if request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for"):
        return True  # came through a tunnel or proxy
    return (request.client.host if request.client else "") not in ("127.0.0.1", "::1", "localhost")


@app.middleware("http")
async def visitors_are_read_only(request: Request, call_next):
    if (not settings.visitors_can_run and request.method not in ("GET", "HEAD", "OPTIONS") and _is_remote(request)
            and not _VISITOR_WRITES.match(request.url.path)):
        return JSONResponse({"detail": "Only the host computer can do this. Shared-link visitors can view "
                                       "results and record human reviews."}, status_code=403)
    return await call_next(request)


@app.get("/api/access")
def access(request: Request):
    """Lets the UI hide host-only buttons from shared-link visitors."""
    return {"remote": _is_remote(request), "can_run": settings.visitors_can_run or not _is_remote(request)}


# ---------------------------------------------------------------- overview
def _case_view(case) -> dict:
    run = runner.get(case.key)
    return {"key": case.key, "label": case.label, "order": case.order,
            "base": {"key": case.base, "label": MODELS[case.base].label, "provider": MODELS[case.base].provider},
            "small_judge": {"key": case.small_judge, "label": MODELS[case.small_judge].label,
                            "provider": MODELS[case.small_judge].provider},
            "large_judge": {"key": case.large_judge, "label": MODELS[case.large_judge].label,
                            "provider": MODELS[case.large_judge].provider},
            "progress": {name: len([r for r in store.load(case.key, name).values() if not r.get("error")])
                         for name in ("generated", "judge_small", "judge_large", "human")},
            "running": bool(run and run.active)}


@app.get("/api/overview")
def overview():
    keys = {"groq": bool(settings.groq_api_key), "gemini": bool(settings.gemini_api_key),
            "nvidia": bool(settings.nvidia_api_key), "openrouter": bool(settings.open_router_api_key),
            "voyage": bool(settings.voyage_api_key)}
    return {
        "cases": [_case_view(c) for c in sorted(CASES.values(), key=lambda c: c.order)],
        "questions": len(store.questions()),
        "question_problems": store.validate_question_set(),
        "keys": keys,
        "ingest": _ingest_job,
    }


# ---------------------------------------------------------------- corpus
_ingest_job: dict = {"state": "idle", "log": [], "started_at": None, "error": None}


@app.get("/api/corpus")
def corpus_status():
    return {**corpus.status(), "ingest": _ingest_job}


@app.get("/api/corpus/plan")
def corpus_plan():
    return corpus.plan()


@app.post("/api/corpus/upload")
async def corpus_upload(files: list[UploadFile]):
    saved = []
    root = Path(settings.corpus_dir)
    root.mkdir(parents=True, exist_ok=True)
    for f in files:
        name = Path(f.filename or "").name
        if Path(name).suffix.lower() not in ingestion.SUPPORTED_EXTENSIONS:
            raise HTTPException(400, f"{name}: only PDF, DOCX, TXT and MD files are supported")
        with (root / name).open("wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(name)
    return {"saved": saved}


@app.post("/api/corpus/ingest")
def corpus_ingest():
    if _ingest_job["state"] == "running":
        raise HTTPException(409, "Ingestion is already running")
    _ingest_job.update(state="running", log=[], error=None,
                       started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def work():
        try:
            result = corpus.ingest(progress=lambda m: _ingest_job["log"].append(m))
            _ingest_job["log"].append(f"Done: {result['total_chunks']} chunks in the corpus")
            _ingest_job["state"] = "done"
        except Exception as e:  # noqa: BLE001 - shown in the UI
            log.exception("Ingestion failed")
            _ingest_job.update(state="error", error=f"{type(e).__name__}: {str(e)[:400]}")

    threading.Thread(target=work, name="ingest", daemon=True).start()
    return _ingest_job


# ---------------------------------------------------------------- question set
@app.get("/api/questions")
def question_set():
    ex = store.expected()
    return {"questions": [{**q, "expected": ex.get(q["id"])} for q in store.questions()],
            "problems": store.validate_question_set()}


# ---------------------------------------------------------------- runs
class StartRequest(BaseModel):
    limit: int | None = None


def _case_or_404(case: str):
    if case not in CASES:
        raise HTTPException(404, f"Unknown case {case}")
    return CASES[case]


@app.post("/api/runs/{case}/start")
def run_start(case: str, body: StartRequest | None = None):
    _case_or_404(case)
    if _ingest_job["state"] == "running":
        raise HTTPException(409, "Wait for ingestion to finish first")
    try:
        return runner.start(case, (body.limit if body else None) or None).view()
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e


@app.post("/api/runs/{case}/stop")
def run_stop(case: str):
    _case_or_404(case)
    runner.stop(case)
    return {"stopping": True}


@app.get("/api/runs/{case}")
def run_status(case: str):
    _case_or_404(case)
    run = runner.get(case)
    return run.view() if run else {"case": case, "active": False, "lanes": None, "log": []}


class ResetRequest(BaseModel):
    target: Literal["generated", "judge_small", "judge_large", "all"]


@app.post("/api/runs/{case}/reset")
def run_reset(case: str, body: ResetRequest):
    _case_or_404(case)
    run = runner.get(case)
    if run and run.active:
        raise HTTPException(409, "Stop the run before resetting results")
    if body.target in ("generated", "all") and any((r := runner.get(c)) and r.active for c in CASES):
        # The answers are shared by every case.
        raise HTTPException(409, "The answers are shared by both cases: stop every run before resetting them")
    for name in (["generated", "judge_small", "judge_large"] if body.target == "all" else [body.target]):
        store.reset(case, name)
    return {"reset": body.target}


# ---------------------------------------------------------------- results and human review
@app.get("/api/results/{case}")
def results(case: str):
    _case_or_404(case)
    ex = store.expected()
    generated = store.load(case, "generated")
    small, large = store.load(case, "judge_small"), store.load(case, "judge_large")
    human = store.load(case, "human")
    return {"case": _case_view(CASES[case]), "items": [
        {"question": q, "expected": ex.get(q["id"]), "generated": generated.get(q["id"]),
         "small": small.get(q["id"]), "large": large.get(q["id"]), "human": human.get(q["id"])}
        for q in store.questions()]}


class HumanVerdict(BaseModel):
    verdict: Literal["pass", "partial", "fail"]
    note: str = ""
    reviewer: str = ""
    agrees_with: Literal["small", "large", "both", "neither"] | None = None


@app.put("/api/results/{case}/{qid}/human")
def set_human(case: str, qid: str, body: HumanVerdict):
    _case_or_404(case)
    if qid not in {q["id"] for q in store.questions()}:
        raise HTTPException(404, f"Unknown question {qid}")
    record = {**body.model_dump(), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    store.save_item(case, "human", qid, record)
    return record


@app.delete("/api/results/{case}/{qid}/human")
def clear_human(case: str, qid: str):
    _case_or_404(case)
    data = store.load(case, "human")
    data.pop(qid, None)
    store.save(case, "human", data)
    return {"cleared": qid}


# ---------------------------------------------------------------- metrics and export
@app.get("/api/metrics")
def metrics_compare():
    return {"cases": metrics.compare_cases()}


@app.get("/api/metrics/{case}")
def metrics_case(case: str):
    _case_or_404(case)
    return metrics.compute(case)


@app.get("/api/export/{case}.csv", response_class=PlainTextResponse)
def export_csv(case: str):
    _case_or_404(case)
    return PlainTextResponse(metrics.to_csv(case), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{case}_results.csv"'})


@app.get("/api/export/{case}.json")
def export_json(case: str):
    _case_or_404(case)
    return {"metrics": metrics.compute(case), **results(case)}


# ---------------------------------------------------------------- the built portal (frontend/dist)
_DIST = PROJECT_ROOT / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def portal(path: str):
        target = _DIST / path
        if path and target.is_file():
            return FileResponse(target)
        # index.html names the current build's files, so browsers must re-check it or they keep an old page.
        return FileResponse(_DIST / "index.html", headers={"Cache-Control": "no-cache"})
