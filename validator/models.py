"""One way to call every model: chat(model_key, system, user) -> ChatResult.

All models run at temperature 0. Errors are sorted into three kinds the runner can act on:
    RateLimited       wait `wait_seconds`, then try again (daily=True: the day's quota is used up)
    ModelUnavailable  the model is retired or not enabled for this key: use its fallback
    other exceptions  a real failure, recorded on the question
"""
import logging
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache

from langchain_core.messages import HumanMessage, SystemMessage

from validator.config import MODELS, ModelSpec, settings

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 240  # seconds; Gemma takes ~60-110 s on a judge call
# NVIDIA's free endpoints queue requests: Step 5 took 17 s to over 4 min per call in testing (2026-11-05).
NVIDIA_TIMEOUT = 480


class RateLimited(Exception):
    def __init__(self, model: str, wait_seconds: float, daily: bool, message: str):
        super().__init__(message)
        self.model, self.wait_seconds, self.daily = model, wait_seconds, daily


class ModelUnavailable(Exception):
    pass


@dataclass
class ChatResult:
    text: str
    model_key: str                 # the model that actually answered (a fallback, if one was used)
    model_id: str
    latency_s: float
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- clients
@lru_cache
def _client(key: str, max_tokens: int):
    spec = MODELS[key]
    if spec.provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=spec.model_id, temperature=0, api_key=settings.groq_api_key, max_retries=0,
                        max_tokens=max_tokens, timeout=REQUEST_TIMEOUT)
    if spec.provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=spec.model_id, temperature=0, google_api_key=settings.gemini_api_key,
                                      max_retries=0, max_output_tokens=max_tokens, timeout=REQUEST_TIMEOUT)
    from langchain_openai import ChatOpenAI
    if spec.provider == "nvidia":
        base, api_key = settings.nvidia_base_url, settings.nvidia_api_key
    else:
        base, api_key = settings.open_router_base_url, settings.open_router_api_key
    return ChatOpenAI(model=spec.model_id, temperature=0, base_url=base, api_key=api_key, max_retries=0,
                      max_tokens=max_tokens,
                      timeout=NVIDIA_TIMEOUT if spec.provider == "nvidia" else REQUEST_TIMEOUT)


# ---------------------------------------------------------------- error sorting
def _parse_wait(message: str) -> float | None:
    """Seconds to wait, from "try again in 7m12.5s", "retry in 31.2s", "retryDelay': '31s'"."""
    m = re.search(r"(?:try again in|retry in|retryDelay['\"]?:\s*['\"]?)\s*"
                  r"(?:(\d+)h)?(?:(\d+)m(?!s))?(?:(\d+(?:\.\d+)?)s)?", message, re.I)
    if not m:
        return None
    h, mins, secs = m.groups()
    total = int(h or 0) * 3600 + int(mins or 0) * 60 + float(secs or 0)
    return total or None


def _classify(spec: ModelSpec, error: Exception) -> Exception:
    text = str(error)
    status = getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)
    lowered = text.lower()
    if status == 429 or "rate limit" in lowered or "resource_exhausted" in lowered or "429" in text[:40]:
        daily = any(s in lowered for s in ("per day", "tpd", "rpd", "perday", "daily"))
        wait = _parse_wait(text)
        if wait is None:
            wait = 3600.0 if daily else 60.0
        return RateLimited(spec.key, wait + 2, daily, text[:300])
    if status in (404, 410) or "end of life" in lowered or "not found for account" in lowered:
        return ModelUnavailable(f"{spec.label} is unavailable: {text[:200]}")
    return error


def _text_of(content) -> str:
    """Message content as plain text. Gemini can return a list of parts; reasoning blocks are dropped."""
    if isinstance(content, list):
        content = "".join(p.get("text", "") if isinstance(p, dict) and p.get("type", "text") == "text" else
                          (p if isinstance(p, str) else "") for p in content)
    return re.sub(r"<think>.*?</think>", "", content or "", flags=re.S).strip()


# ---------------------------------------------------------------- the call
def chat(key: str, system: str, user: str, max_tokens: int = 2048) -> ChatResult:
    """One call. Transient failures (network, 5xx) are retried here; rate limits and retired models are
    raised for the caller. If the model is unavailable and has a fallback, the fallback answers."""
    spec = MODELS[key]
    # Some reasoning models spend the whole budget thinking and return nothing: they get a larger floor.
    max_tokens = max(max_tokens, spec.min_output_tokens or 0)
    messages = [SystemMessage(system), HumanMessage(user)]
    last: Exception | None = None
    for attempt in range(3):
        started = time.perf_counter()
        try:
            reply = _client(key, max_tokens).invoke(messages)
        except Exception as e:  # noqa: BLE001 - sorted below
            sorted_error = _classify(spec, e)
            if isinstance(sorted_error, ModelUnavailable) and spec.fallback:
                log.warning("%s; switching to %s", sorted_error, spec.fallback)
                result = chat(spec.fallback, system, user, max_tokens)
                result.notes.append(f"{spec.label} was unavailable; {MODELS[spec.fallback].label} answered instead")
                return result
            if isinstance(sorted_error, (RateLimited, ModelUnavailable)):
                raise sorted_error from e
            last = e
            log.warning("%s call failed (attempt %d): %s", spec.label, attempt + 1, str(e)[:200])
            time.sleep(5 * (attempt + 1))
            continue
        usage = getattr(reply, "usage_metadata", None) or {}
        return ChatResult(
            text=_text_of(reply.content),
            model_key=key,
            model_id=spec.model_id,
            latency_s=round(time.perf_counter() - started, 2),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            reasoning_tokens=int((usage.get("output_token_details") or {}).get("reasoning") or 0),
        )
    raise last  # type: ignore[misc]
