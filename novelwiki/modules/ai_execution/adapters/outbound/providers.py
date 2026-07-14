import httpx
import logging
import asyncio
import math
import time
from openai import AsyncOpenAI
from novelwiki.platform.config import settings
from novelwiki.platform.observability.logging import log_event
from novelwiki.modules.ai_execution.application.errors import BudgetExhausted

logger = logging.getLogger(__name__)


def _payload_chars(value) -> int:
    """Measure provider payload size without logging its story-bearing content."""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(_payload_chars(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_payload_chars(item) for item in value)
    return 0


def _usage_fields(response) -> dict:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    return {
        "input_tokens": getattr(usage, "prompt_tokens", None)
        or getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None)
        or getattr(usage, "output_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def _http_status(error: Exception) -> int | None:
    response = getattr(error, "response", None)
    return getattr(response, "status_code", None)

# Lazy initialized OpenAI client for Chat and Embeddings
_openai_client = None

def get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        api_key = settings.OPENROUTER_API_KEY
        if not api_key:
            logger.warning("OPENROUTER_API_KEY is not set in environments. API calls will fail.")
        _openai_client = AsyncOpenAI(
            api_key=api_key,
            base_url=settings.OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": settings.OPENROUTER_REFERER,
                "X-OpenRouter-Title": settings.OPENROUTER_TITLE,
            }
        )
    return _openai_client

def normalize_vector(v: list[float]) -> list[float]:
    """Applies L2 normalization to a vector for cosine similarity operations."""
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0:
        return v
    return [x / norm for x in v]

def _validate_dim(vec: list[float]) -> list[float]:
    """Guards the EMBED_DIM <-> pgvector column invariant: a wrong-dimension
    embedding must never be silently stored (the DB cast would fail cryptically)."""
    if len(vec) != settings.EMBED_DIM:
        raise ValueError(
            f"Embedding dimension mismatch: model '{settings.EMBED_MODEL}' returned "
            f"{len(vec)} dims but settings.EMBED_DIM={settings.EMBED_DIM}. "
            f"Set EMBED_DIM to match the model and re-run the schema migration."
        )
    return vec

async def call_chat_completion(
    model: str, 
    messages: list[dict], 
    temperature: float = 0.0, 
    response_format: dict = None,
    reasoning: str = "high"
) -> str:
    """Invokes OpenRouter Chat Completions API with exponential backoff retries."""
    client = get_openai_client()
    backoff = 1.0
    started = time.monotonic()
    log_event(
        logger, logging.INFO, "ai.provider_call_started",
        f"Starting OpenRouter chat completion with model {model}.",
        provider="openrouter", operation="chat_completion", model=model,
        messages=len(messages), input_chars=_payload_chars(messages),
        temperature=temperature, reasoning_effort=reasoning, max_attempts=5,
        structured_response=bool(response_format),
    )
    for attempt in range(5):
        attempt_started = time.monotonic()
        try:
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "reasoning_effort": reasoning,
            }
            if response_format:
                kwargs["response_format"] = response_format
                
            response = await client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""
            log_event(
                logger, logging.INFO, "ai.provider_call_completed",
                f"OpenRouter chat completion with model {model} succeeded on attempt {attempt + 1}.",
                provider="openrouter", operation="chat_completion", model=model,
                attempt=attempt + 1, max_attempts=5, output_chars=len(content),
                attempt_duration_ms=round((time.monotonic() - attempt_started) * 1000, 2),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                **_usage_fields(response),
            )
            return content
        except Exception as e:
            terminal = attempt == 4
            log_event(
                logger, logging.ERROR if terminal else logging.WARNING,
                "ai.provider_call_failed",
                f"OpenRouter chat completion with model {model} failed on attempt {attempt + 1}.",
                exc_info=True if terminal else None,
                provider="openrouter", operation="chat_completion", model=model,
                attempt=attempt + 1, max_attempts=5, retry_scheduled=not terminal,
                retry_delay_seconds=None if terminal else backoff,
                http_status=_http_status(e), error_type=type(e).__name__, error=str(e),
                attempt_duration_ms=round((time.monotonic() - attempt_started) * 1000, 2),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            if attempt == 4:
                raise
            await asyncio.sleep(backoff)
            backoff *= 2.0
    return ""

def _embed_kwargs(inp) -> dict:
    kwargs = {"model": settings.EMBED_MODEL, "input": inp}
    if settings.EMBED_REQUEST_DIMENSIONS:
        kwargs["dimensions"] = settings.EMBED_DIM
    return kwargs


async def get_embedding(text: str) -> list[float]:
    """Generates a single normalized vector embedding."""
    client = get_openai_client()
    backoff = 1.0
    started = time.monotonic()
    log_event(
        logger, logging.INFO, "ai.provider_call_started",
        f"Starting single embedding with model {settings.EMBED_MODEL}.",
        provider="openrouter", operation="embedding", model=settings.EMBED_MODEL,
        input_items=1, input_chars=len(text), max_attempts=5,
        requested_dimensions=settings.EMBED_DIM if settings.EMBED_REQUEST_DIMENSIONS else None,
    )
    for attempt in range(5):
        attempt_started = time.monotonic()
        try:
            response = await client.embeddings.create(**_embed_kwargs(text))
            raw_emb = response.data[0].embedding
            result = _validate_dim(normalize_vector(raw_emb))
            log_event(
                logger, logging.INFO, "ai.provider_call_completed",
                f"Single embedding with model {settings.EMBED_MODEL} succeeded on attempt {attempt + 1}.",
                provider="openrouter", operation="embedding", model=settings.EMBED_MODEL,
                attempt=attempt + 1, max_attempts=5, output_vectors=1,
                embedding_dimensions=len(result),
                attempt_duration_ms=round((time.monotonic() - attempt_started) * 1000, 2),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                **_usage_fields(response),
            )
            return result
        except Exception as e:
            terminal = attempt == 4
            log_event(
                logger, logging.ERROR if terminal else logging.WARNING,
                "ai.provider_call_failed",
                f"Single embedding with model {settings.EMBED_MODEL} failed on attempt {attempt + 1}.",
                exc_info=True if terminal else None,
                provider="openrouter", operation="embedding", model=settings.EMBED_MODEL,
                attempt=attempt + 1, max_attempts=5, retry_scheduled=not terminal,
                retry_delay_seconds=None if terminal else backoff,
                http_status=_http_status(e), error_type=type(e).__name__, error=str(e),
                attempt_duration_ms=round((time.monotonic() - attempt_started) * 1000, 2),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            if attempt == 4:
                raise
            await asyncio.sleep(backoff)
            backoff *= 2.0
    return []

async def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Generates a batch of normalized vector embeddings, preserving original order."""
    if not texts:
        return []
    client = get_openai_client()
    backoff = 1.0
    started = time.monotonic()
    log_event(
        logger, logging.INFO, "ai.provider_call_started",
        f"Starting batch embedding of {len(texts)} items with model {settings.EMBED_MODEL}.",
        provider="openrouter", operation="batch_embedding", model=settings.EMBED_MODEL,
        input_items=len(texts), input_chars=sum(len(text) for text in texts),
        max_attempts=5,
        requested_dimensions=settings.EMBED_DIM if settings.EMBED_REQUEST_DIMENSIONS else None,
    )
    for attempt in range(5):
        attempt_started = time.monotonic()
        try:
            response = await client.embeddings.create(**_embed_kwargs(texts))
            # OpenRouter may return out of order indices; sort them to match original order
            sorted_data = sorted(response.data, key=lambda x: x.index)
            embeddings = [_validate_dim(normalize_vector(item.embedding)) for item in sorted_data]
            log_event(
                logger, logging.INFO, "ai.provider_call_completed",
                f"Batch embedding with model {settings.EMBED_MODEL} succeeded on attempt {attempt + 1}.",
                provider="openrouter", operation="batch_embedding", model=settings.EMBED_MODEL,
                attempt=attempt + 1, max_attempts=5,
                output_vectors=len(embeddings), embedding_dimensions=(len(embeddings[0]) if embeddings else 0),
                attempt_duration_ms=round((time.monotonic() - attempt_started) * 1000, 2),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                **_usage_fields(response),
            )
            return embeddings
        except Exception as e:
            terminal = attempt == 4
            log_event(
                logger, logging.ERROR if terminal else logging.WARNING,
                "ai.provider_call_failed",
                f"Batch embedding with model {settings.EMBED_MODEL} failed on attempt {attempt + 1}.",
                exc_info=True if terminal else None,
                provider="openrouter", operation="batch_embedding", model=settings.EMBED_MODEL,
                attempt=attempt + 1, max_attempts=5, retry_scheduled=not terminal,
                retry_delay_seconds=None if terminal else backoff,
                http_status=_http_status(e), error_type=type(e).__name__, error=str(e),
                attempt_duration_ms=round((time.monotonic() - attempt_started) * 1000, 2),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            if attempt == 4:
                raise
            await asyncio.sleep(backoff)
            backoff *= 2.0
    return []

# ── Unified provider routing (text → OpenRouter, pixels → Gemini) ───────────
# The codex/translation/segmentation work is text and goes to OpenRouter (above).
# Vision work (scanned-PDF OCR escalation) goes to Gemini's free tier through its
# OpenAI-compatible endpoint, guarded by a persistent daily budget + an RPM limiter.

_gemini_client = None
# One in-process limiter for the whole app: serialize a minimum interval between
# Gemini calls to stay under GEMINI_RPM (the budget table guards the daily cap).
_gemini_lock = asyncio.Lock()
_gemini_last_call = 0.0


def get_gemini_client() -> AsyncOpenAI:
    global _gemini_client
    if _gemini_client is None:
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            logger.warning("GEMINI_API_KEY is not set; vision calls will fail.")
        _gemini_client = AsyncOpenAI(api_key=api_key, base_url=settings.GEMINI_BASE_URL)
    return _gemini_client


async def _charge_gemini_budget() -> int:
    """Atomically increments today's Gemini usage and returns the new total. Raises
    BudgetExhausted (and refunds the increment) once over GEMINI_DAILY_BUDGET, so the
    cap survives restarts. Lazily imported pool to avoid a circular import at module load."""
    from novelwiki.platform.database import get_db_pool
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        used = await conn.fetchval(
            """
            INSERT INTO provider_budget (provider, day, used)
            VALUES ('gemini', CURRENT_DATE, 1)
            ON CONFLICT (provider, day) DO UPDATE SET used = provider_budget.used + 1
            RETURNING used;
            """
        )
        if used > settings.GEMINI_DAILY_BUDGET:
            await conn.execute(
                "UPDATE provider_budget SET used = used - 1 WHERE provider = 'gemini' AND day = CURRENT_DATE;"
            )
            raise BudgetExhausted(
                f"Gemini daily budget of {settings.GEMINI_DAILY_BUDGET} reached; pausing until tomorrow."
            )
    used = int(used)
    log_event(
        logger, logging.INFO, "ai.provider_budget_charged",
        f"Charged one Gemini vision request; {used}/{settings.GEMINI_DAILY_BUDGET} used today.",
        provider="gemini", operation="vision_completion",
        budget_used=used, budget_limit=settings.GEMINI_DAILY_BUDGET,
        budget_remaining=max(0, settings.GEMINI_DAILY_BUDGET - used),
    )
    return used


async def gemini_budget_remaining(daily_budget: int) -> int:
    from novelwiki.platform.database import get_db_pool
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        used = await connection.fetchval(
            "SELECT used FROM provider_budget WHERE provider='gemini' AND day=CURRENT_DATE;"
        )
    return max(0, int(daily_budget) - int(used or 0))


async def _gemini_rate_gate():
    """Sleeps just enough to keep at least 60/RPM seconds between Gemini calls."""
    global _gemini_last_call
    min_interval = 60.0 / max(1, settings.GEMINI_RPM)
    async with _gemini_lock:
        wait = min_interval - (asyncio.get_event_loop().time() - _gemini_last_call)
        if wait > 0:
            log_event(
                logger, logging.INFO, "ai.provider_rate_limit_wait",
                f"Waiting {wait:.2f}s for the configured Gemini rate limit.",
                provider="gemini", operation="vision_completion",
                wait_seconds=round(wait, 3), configured_rpm=settings.GEMINI_RPM,
            )
            await asyncio.sleep(wait)
        _gemini_last_call = asyncio.get_event_loop().time()


async def call_vision_completion(
    messages: list[dict], model: str = None, temperature: float = 0.0
) -> str:
    """Routes a (possibly image-bearing) chat to Gemini. `messages` may contain
    OpenAI-style content parts with `image_url` data URLs. Enforces the daily budget
    and RPM limit, with exponential backoff mirroring call_chat_completion."""
    await _charge_gemini_budget()      # raises BudgetExhausted if over the cap
    await _gemini_rate_gate()
    client = get_gemini_client()
    backoff = 1.0
    selected_model = model or settings.GEMINI_VISION_MODEL
    started = time.monotonic()
    log_event(
        logger, logging.INFO, "ai.provider_call_started",
        f"Starting Gemini vision completion with model {selected_model}.",
        provider="gemini", operation="vision_completion", model=selected_model,
        messages=len(messages), input_chars=_payload_chars(messages),
        temperature=temperature, max_attempts=5,
    )
    for attempt in range(5):
        attempt_started = time.monotonic()
        try:
            response = await client.chat.completions.create(
                model=selected_model,
                messages=messages,
                temperature=temperature,
            )
            content = response.choices[0].message.content or ""
            log_event(
                logger, logging.INFO, "ai.provider_call_completed",
                f"Gemini vision completion with model {selected_model} succeeded on attempt {attempt + 1}.",
                provider="gemini", operation="vision_completion", model=selected_model,
                attempt=attempt + 1, max_attempts=5, output_chars=len(content),
                attempt_duration_ms=round((time.monotonic() - attempt_started) * 1000, 2),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                **_usage_fields(response),
            )
            return content
        except Exception as e:
            terminal = attempt == 4
            log_event(
                logger, logging.ERROR if terminal else logging.WARNING,
                "ai.provider_call_failed",
                f"Gemini vision completion with model {selected_model} failed on attempt {attempt + 1}.",
                exc_info=True if terminal else None,
                provider="gemini", operation="vision_completion", model=selected_model,
                attempt=attempt + 1, max_attempts=5, retry_scheduled=not terminal,
                retry_delay_seconds=None if terminal else backoff,
                http_status=_http_status(e), error_type=type(e).__name__, error=str(e),
                attempt_duration_ms=round((time.monotonic() - attempt_started) * 1000, 2),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            if attempt == 4:
                raise
            await asyncio.sleep(backoff)
            backoff *= 2.0
    return ""


async def call_llm(
    messages: list[dict],
    *,
    needs_vision: bool,
    model: str = None,
    temperature: float = 0.0,
    response_format: dict = None,
) -> str:
    """The provider router: pixels go to Gemini vision; everything else goes to
    OpenRouter (defaulting to the segmentation model). Callers don't pick a provider."""
    if needs_vision:
        return await call_vision_completion(messages, model=model, temperature=temperature)
    return await call_chat_completion(
        model=model or settings.SEGMENT_MODEL,
        messages=messages,
        temperature=temperature,
        response_format=response_format,
    )


async def rerank_passages(query: str, documents: list[str], top_n: int = None) -> list[dict]:
    """
    Reranks documents against a query using OpenRouter's /rerank endpoint.
    Returns: [{"index": int, "score": float, "text": str}]
    """
    if not documents:
        return []
    
    if top_n is None:
        top_n = settings.RERANK_TOP_N
        
    api_key = settings.OPENROUTER_API_KEY
    url = f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/rerank"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.OPENROUTER_REFERER,
        "X-OpenRouter-Title": settings.OPENROUTER_TITLE,
    }
    
    payload = {
        "model": settings.RERANK_MODEL,
        "query": query,
        "documents": documents,
        "top_n": top_n
    }
    
    backoff = 1.0
    started = time.monotonic()
    log_event(
        logger, logging.INFO, "ai.provider_call_started",
        f"Starting rerank of {len(documents)} documents with model {settings.RERANK_MODEL}.",
        provider="openrouter", operation="rerank", model=settings.RERANK_MODEL,
        input_documents=len(documents), input_chars=sum(len(item) for item in documents),
        query_chars=len(query), top_n=top_n, max_attempts=5,
    )
    for attempt in range(5):
        attempt_started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                res_data = response.json()
                
                results = []
                for item in res_data.get("results", []):
                    # OpenRouter format: {"index": int, "relevance_score": float, "document": {"text": str}}
                    doc_obj = item.get("document", {})
                    text_val = doc_obj.get("text", "") if isinstance(doc_obj, dict) else str(doc_obj)
                    results.append({
                        "index": int(item.get("index")),
                        "score": float(item.get("relevance_score")),
                        "text": text_val
                    })
                log_event(
                    logger, logging.INFO, "ai.provider_call_completed",
                    f"Rerank with model {settings.RERANK_MODEL} succeeded on attempt {attempt + 1}.",
                    provider="openrouter", operation="rerank", model=settings.RERANK_MODEL,
                    attempt=attempt + 1, max_attempts=5, output_results=len(results),
                    attempt_duration_ms=round((time.monotonic() - attempt_started) * 1000, 2),
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                )
                return results
        except Exception as e:
            terminal = attempt == 4
            log_event(
                logger, logging.ERROR if terminal else logging.WARNING,
                "ai.provider_call_failed",
                f"Rerank with model {settings.RERANK_MODEL} failed on attempt {attempt + 1}.",
                exc_info=True if terminal else None,
                provider="openrouter", operation="rerank", model=settings.RERANK_MODEL,
                attempt=attempt + 1, max_attempts=5, retry_scheduled=not terminal,
                retry_delay_seconds=None if terminal else backoff,
                http_status=_http_status(e), error_type=type(e).__name__, error=str(e),
                attempt_duration_ms=round((time.monotonic() - attempt_started) * 1000, 2),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            if attempt == 4:
                raise
            await asyncio.sleep(backoff)
            backoff *= 2.0
    return []
