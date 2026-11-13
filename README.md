# Agentic-RAG Pipeline Validator

A portal that tests the correctness of the day7 Agentic-RAG system:

1. **Corpus**: hand-picked files, ingested with day7's pipeline (clean → 1,000-char chunks → Gemini embeddings +
   BM25 → Qdrant).
2. **Question set**: `data/questions.json`, plus the complementary `data/expected.json`. The expected file is an
   abstract rubric of hints and concepts the answer must or should contain, not the answer itself.
3. **Base agent** (gpt-oss-120b, as in day7) answers every question once from the ingested corpus → `data/runs/generated.json`. Both cases share this file, so all four judges grade exactly the same answers.
4. **Two judges**, a smaller and a larger model, each receive the expected and generated answers. Each one
   **searches the corpus itself** and grades every rubric point → `judge_small.json`, `judge_large.json`.
5. **Metrics** for the base agent and each judge, plus judge-vs-judge agreement.
6. **Human checker** reviews both judges side by side and gives the final verdict → `human.json`.


**Results:** see [RESULTS.md](RESULTS.md) for the findings from the full run (both cases, all 50 questions).
## Test cases

Both cases use day7's answer model, gpt-oss-120b, as the base; only the judges change. No judge is used twice,
and no judge is the base model, so no judge ever grades its own answers.

| | Smaller judge | Base (answers with RAG) | Larger judge | Runs |
|---|---|---|---|---|
| **Case 2** | gpt-oss-20b (Groq) | gpt-oss-120b (Groq) | Nemotron 3.5 Super 120B (NVIDIA) | first |
| **Case 1** | Gemma 4 31B (Google AI Studio) | gpt-oss-120b (Groq) | Nemotron 3 Ultra 550B (NVIDIA) | second |

Case 2's larger judge was Step 5 Preview until 2026-11-06. On the same judge prompts Nemotron 3.5 Super took a
median 24 s per question against 56 s (slowest 31 s against 180 s), so it replaced Step 5.

Fallbacks, used only if NVIDIA retires a model: Nemotron 3.5 Super (NVIDIA) → the same model on OpenRouter, and Nemotron Ultra
(NVIDIA) → Nemotron Ultra (OpenRouter). Every result records the model that actually answered.

Free-tier limits (checked 2026-11-05):
- Groq, per model: 200K tokens / 1,000 requests a day, 8K tokens a minute.
- Gemma 4 31B: 30 requests and 16K tokens a minute, 14,400 a day.
- Gemini Embedding 1: 100 requests and 30K tokens a minute, 1,000 a day. Every chunk and every search query
  counts; queries are cached.
- NVIDIA: up to ~40 requests a minute (daily limit not published).
- OpenRouter free: 50 requests a day, shared by all free models.
- Voyage rerank without a payment method: 3 requests a minute.

## Run it

```powershell
# once
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd frontend; npm install; npm run build; cd ..

# the portal (backend + built frontend) on http://127.0.0.1:8100
.venv\Scripts\python -m uvicorn validator.api:app --host 127.0.0.1 --port 8100
```

For frontend development, run `npm run dev` in `frontend/` (http://127.0.0.1:5174, proxied to the backend).

API keys are read from `../day7/.env` (where they already are), then from this folder's `.env`, if present,
which overrides them. Needed: `GROQ_API_KEY`, `GEMINI_API_KEY`, `NVIDIA_API_KEY`, `VOYAGE_API_KEY`, and
`OPEN_ROUTER_API_KEY` for the fallbacks.

The portal has no login. It listens on 127.0.0.1 only.

### Sharing a link

```powershell
tools\cloudflared\cloudflared.exe tunnel --no-autoupdate --url http://127.0.0.1:8100
```

This prints a public `https://….trycloudflare.com` address (free, no account). It changes every time the tunnel
starts, and works only while this computer, the portal and the tunnel are running. Anyone with the link can view
everything and record human reviews. Starting, stopping or resetting runs, uploading files and ingesting are refused
for them (403) and hidden in their UI; those work only on this computer.

### Command line (same engine, no browser)

```powershell
.venv\Scripts\python -m validator status
.venv\Scripts\python -m validator plan           # embedding requests the next ingest will cost
.venv\Scripts\python -m validator ingest
.venv\Scripts\python -m validator validate       # checks questions.json / expected.json
.venv\Scripts\python -m validator run case2 --limit 3   # smoke test; omit --limit for the full set
.venv\Scripts\python -m validator metrics
```

Use either the portal or the command line, not both at once: they share the on-disk vector store.

## How each part works

**Base agent** (`validator/base_agent.py`) is day7's document path without the router: hybrid search (dense +
BM25, RRF) → Voyage `rerank-2.5` → confidence zone → MMR → answer with day7's own prompt and `[n]` citations →
day7's code citation check (no model). It deliberately skips the two steps that would call a *different* model:
the mid-zone query rewrite (gpt-oss-20b in day7) and the LLM answer check (gpt-oss-120b in day7). The judges do
the checking instead.

**Judges** (`validator/judge.py`) make two calls per question, the same for every judge:
1. *plan*: read the question, rubric and answer, and write up to 3 search queries;
2. *grade*: we run those searches over the whole corpus (hybrid, no reranker; up to 8 passages). The judge then
   grades every rubric point (`covered / partial / missing`, or `violated / respected` for must-not points), and
   gives grounding, unsupported and contradicted claims, a verdict (`pass / partial / fail`), a 0-10 score,
   confidence and a reason.

The judges never see the passages the base agent used, so their evidence is independent of the system under test.

**Runner** (`validator/runner.py`): three lanes (base, smaller judge, larger judge) in parallel threads. Judges
start on each answer as soon as it exists. Everything is saved after each question, so a stopped run resumes.
Rate limits are waited out, including the daily reset, and results whose inputs changed are redone
automatically.

## Metrics (`validator/metrics.py`)

- **Base agent**: answered, answerable questions answered, unanswerable questions correctly declined, match zones,
  mean rerank relevance, source-file hit rate and MRR (when a question names its source file), citation check pass
  rate and support, latency, tokens.
- **Each judge**: verdict counts, pass and pass-or-partial rate, mean score, must/should coverage
  (partial = 0.5), must-not violations, grounding, unsupported and contradicted claims, confidence,
  self-consistency (does its verdict follow from its own rubric grades?), pass rate by question type, latency,
  calls, tokens.
- **Agreement** (judge vs judge, and each judge vs the human): same-verdict rate, Cohen's kappa, weighted kappa,
  rubric-point agreement, score correlation, mean score gap, confusion table, list of disagreements.

Export per case: CSV (one row per question) and JSON (everything).

## File formats

`data/questions.json`
```json
[{"id": "Q01", "question": "…", "type": "factual", "source_files": ["report.pdf"]}]
```
`source_files` is optional. It feeds only the retrieval metrics and is never shown to the judges.

`data/expected.json`
```json
[{"id": "Q01", "answerable": true,
  "must_include": ["concept the answer has to convey"],
  "should_include": ["nice-to-have detail"],
  "must_not_include": ["a likely wrong claim"],
  "notes": "optional hint for the graders"}]
```

## Tests

```powershell
.venv\Scripts\python -m pytest -q tests
```
