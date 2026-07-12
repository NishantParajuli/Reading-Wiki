import logging
from novelwiki.platform.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def rerank_hits(
    query: str, 
    hits: list[dict], 
    top_n: int = None,
    *,
    runtime,
) -> list[dict]:
    """
    Reranks a list of candidate chunks against a query using Cohere Rerank on OpenRouter.
    Maps results back to the original list items.
    If the external Rerank API fails, falls back gracefully to the top RRF hits.
    """
    if not hits:
        return []
        
    if top_n is None:
        top_n = settings.RERANK_TOP_N
        
    # OpenRouter rerank expects a list of texts
    texts = [h["text"] for h in hits]
    
    try:
        logger.info(f"Sending {len(texts)} candidates to Cohere Rerank...")
        reranked_results = await runtime.ai.rerank_passages(query, texts, top_n=top_n)
        
        reranked_hits = []
        for item in reranked_results:
            idx = item["index"]
            if idx < len(hits):
                orig_hit = hits[idx]
                reranked_hits.append({
                    "id": orig_hit["id"],
                    "chapter": orig_hit["chapter"],
                    "text": orig_hit["text"],
                    "rerank_score": item["score"]
                })
        return reranked_hits
    except Exception as e:
        logger.error(f"Reranking failed: {e}. Falling back to top {top_n} fused hits.")
        # Fallback to top_n from original list
        return hits[:top_n]
