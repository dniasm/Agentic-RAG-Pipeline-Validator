"""Settings and the two test cases.

API keys are read from day7's .env (where they already live), then from this project's own .env, which
overrides it. Retrieval settings are the same values day7 uses, so the base agent searches exactly like the
real system.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DAY7_ENV = PROJECT_ROOT.parent / "day7" / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(DAY7_ENV, PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Provider keys ---
    groq_api_key: str = ""
    gemini_api_key: str = ""
    nvidia_api_key: str = ""
    open_router_api_key: str = ""
    voyage_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    open_router_base_url: str = "https://openrouter.ai/api/v1"

    # --- Files ---
    corpus_dir: str = str(DATA_DIR / "corpus")
    questions_path: str = str(DATA_DIR / "questions.json")
    expected_path: str = str(DATA_DIR / "expected.json")
    runs_dir: str = str(DATA_DIR / "runs")
    # Used by the embedding cache (it stores its SQLite file next to this path).
    database_path: str = str(DATA_DIR / "state" / "validator.db")

    # --- Embeddings (Gemini), same as day7 ---
    embedding_model: str = "models/gemini-embedding-001"
    embedding_dim: int = 768

    # --- Vector store: this project's own embedded Qdrant ---
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_path: str = str(DATA_DIR / "qdrant")
    collection_name: str = "validator_corpus"
    corpus_owner: str = "corpus"  # every chunk is stored under this one "user"

    # --- Ingestion, same as day7 ---
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # --- Retrieval, same as day7 ---
    retrieval_k: int = 6
    retrieval_mode: str = "hybrid"
    hybrid_candidates: int = 20
    rrf_k: int = 60
    bm25_k1: float = 1.2
    bm25_b: float = 0.75
    bm25_avg_len: float = 120.0
    rerank_enabled: bool = True
    reranker_provider: str = "voyage"
    voyage_rerank_model: str = "rerank-2.5"
    voyage_rerank_timeout: float = 15.0
    reranker_local_fallback: bool = False
    voyage_relevance_high: float = 0.55
    voyage_relevance_low: float = 0.45
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_max_length: int = 256
    rerank_candidates: int = 20
    rerank_top_n: int = 12
    mmr_lambda: float = 0.7
    relevance_high: float = 0.05
    relevance_low: float = 0.01
    min_relevance_score: float = 0.45

    # --- Shared link ---
    # False (user's choice, 2026-11-09): link visitors can view everything and record human reviews, nothing else.
    # True: they can also start/stop/reset runs, upload and ingest. Override with VISITORS_CAN_RUN in .env.
    visitors_can_run: bool = False

    # --- Judges ---
    judge_max_queries: int = 3          # search queries a judge may write per question
    judge_passages_per_query: int = 3   # passages kept from each of its searches
    # 6 x 700 (was 8 x 900, 2026-11-06): table text is ~1.7 characters per token, and 8 x 900 put gpt-oss-20b at
    # ~6K tokens a question, over Groq's 200K a day for 50 questions. Same for every judge, so the comparison stays fair.
    judge_max_passages: int = 6         # total passages shown to the judge
    judge_passage_chars: int = 700      # each passage is cut to this length
    # Groq counts the requested output limit toward its 8K tokens-per-minute cap: prompt (~4K) + this must fit.
    judge_max_output_tokens: int = 3000
    answer_max_output_tokens: int = 2048


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


# ---------------------------------------------------------------- models and cases
@dataclass(frozen=True)
class ModelSpec:
    key: str                      # short name used in file names and the UI
    label: str                    # display name
    provider: str                 # groq | google | nvidia | openrouter
    model_id: str
    fallback: str | None = None   # key of the model used if this one is retired or unavailable
    min_output_tokens: int | None = None  # floor for max_tokens (reasoning models that think at length)


MODELS: dict[str, ModelSpec] = {m.key: m for m in [
    ModelSpec("gpt-oss-120b", "gpt-oss-120b", "groq", "openai/gpt-oss-120b"),
    ModelSpec("gpt-oss-20b", "gpt-oss-20b", "groq", "openai/gpt-oss-20b"),
    ModelSpec("qwen-27b", "Qwen 27B", "groq", "qwen/qwen3.8-27b"),
    # 2026-11-09: some grade calls spent all 3,000 output tokens thinking and returned no JSON (Q15, Q34 twice).
    ModelSpec("gemma-4-31b", "Gemma 4 31B", "google", "gemma-4-31b-it", min_output_tokens=8000),
    # 2026-11-08: with 3,000 output tokens it sometimes spent ~2,850 on reasoning and cut its JSON short.
    ModelSpec("nemotron-ultra", "Nemotron 3 Ultra 550B", "nvidia", "nvidia/nemotron-3-ultra-550b-a55b",
              fallback="nemotron-ultra-or", min_output_tokens=8000),
    ModelSpec("step-5", "Step 5 Preview", "nvidia", "stepfun-ai/step-5-preview", fallback="nemotron-super-or"),
    # Measured 2026-11-06 on real judge prompts: median 24 s per question vs 56 s for Step 5 (max 31 s vs 180 s).
    # With 3,000 output tokens it once spent them all on hidden reasoning and replied with nothing.
    ModelSpec("nemotron-super", "Nemotron 3.5 Super 120B", "nvidia", "nvidia/nemotron-3.5-super-vl-120b-a12b",
              fallback="nemotron-super-or", min_output_tokens=8000),
    # Fallbacks only (OpenRouter free tier: 50 requests a day shared by all free models).
    ModelSpec("nemotron-ultra-or", "Nemotron 3 Ultra 550B (OpenRouter)", "openrouter",
              "nvidia/nemotron-3-ultra-550b-a55b:free"),
    ModelSpec("nemotron-super-or", "Nemotron 3.5 Super 120B (OpenRouter)", "openrouter",
              "nvidia/nemotron-3.5-super-vl:free"),
]}


@dataclass(frozen=True)
class Case:
    key: str
    label: str
    base: str          # answers the questions, with access to the ingested corpus
    small_judge: str
    large_judge: str
    order: int         # run order: lower runs first

    @property
    def judges(self) -> dict[str, str]:
        return {"small": self.small_judge, "large": self.large_judge}


CASES: dict[str, Case] = {c.key: c for c in [
    # Both cases use day7's answer model (gpt-oss-120b); only the judge pairs differ.
    # Larger judge was Step 5 until 2026-11-06; Nemotron 3.5 Super is twice as fast on the same prompts.
    Case("case2", "Case 2: gpt-oss-20b + Nemotron 3.5 Super judges", base="gpt-oss-120b", small_judge="gpt-oss-20b",
         large_judge="nemotron-super", order=1),
    Case("case1", "Case 1: Gemma 4 + Nemotron Ultra judges", base="gpt-oss-120b", small_judge="gemma-4-31b",
         large_judge="nemotron-ultra", order=2),
]}
# The answers are generated once and shared by every case (store.SHARED), so the cases must share a base model.
assert len({c.base for c in CASES.values()}) == 1, "every case must use the same base model"


def quiet_noisy_loggers() -> None:
    """Every HTTP request and Google's "AFC is enabled" notice would otherwise flood the log."""
    import logging
    for name in ("httpx", "google_genai.models", "google_genai._api_client"):
        logging.getLogger(name).setLevel(logging.WARNING)
