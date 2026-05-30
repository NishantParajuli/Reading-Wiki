import httpx
import logging
import asyncio
import math
from openai import AsyncOpenAI
from novelwiki.config.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    response_format: dict = None
) -> str:
    """Invokes OpenRouter Chat Completions API with exponential backoff retries."""
    client = get_openai_client()
    backoff = 1.0
    for attempt in range(5):
        try:
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }
            if response_format:
                kwargs["response_format"] = response_format
                
            response = await client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.warning(f"Chat completion error on attempt {attempt + 1}: {e}")
            if attempt == 4:
                raise e
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
    for attempt in range(5):
        try:
            response = await client.embeddings.create(**_embed_kwargs(text))
            raw_emb = response.data[0].embedding
            return _validate_dim(normalize_vector(raw_emb))
        except Exception as e:
            logger.warning(f"Embedding error on attempt {attempt + 1}: {e}")
            if attempt == 4:
                raise e
            await asyncio.sleep(backoff)
            backoff *= 2.0
    return []

async def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Generates a batch of normalized vector embeddings, preserving original order."""
    if not texts:
        return []
    client = get_openai_client()
    backoff = 1.0
    for attempt in range(5):
        try:
            response = await client.embeddings.create(**_embed_kwargs(texts))
            # OpenRouter may return out of order indices; sort them to match original order
            sorted_data = sorted(response.data, key=lambda x: x.index)
            embeddings = [_validate_dim(normalize_vector(item.embedding)) for item in sorted_data]
            return embeddings
        except Exception as e:
            logger.warning(f"Batch embedding error on attempt {attempt + 1}: {e}")
            if attempt == 4:
                raise e
            await asyncio.sleep(backoff)
            backoff *= 2.0
    return []

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
    for attempt in range(5):
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
                return results
        except Exception as e:
            logger.warning(f"Rerank error on attempt {attempt + 1}: {e}")
            if attempt == 4:
                raise e
            await asyncio.sleep(backoff)
            backoff *= 2.0
    return []
