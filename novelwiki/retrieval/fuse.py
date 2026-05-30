import logging
from novelwiki.config.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def reciprocal_rank_fusion(
    sparse_hits: list[dict], 
    dense_hits: list[dict], 
    rrf_k: int = None
) -> list[dict]:
    """
    Fuses sparse and dense hits lists using Reciprocal Rank Fusion (RRF).
    Scores docs as: sum(1 / (rrf_k + rank))
    Returns list sorted by score descending.
    """
    if rrf_k is None:
        rrf_k = settings.RRF_K
        
    scores = {}  # chunk_id -> fused_score
    doc_map = {} # chunk_id -> document metadata
    
    # 1. Process sparse list (1-indexed rank)
    for rank, hit in enumerate(sparse_hits, start=1):
        doc_id = hit["id"]
        doc_map[doc_id] = hit
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
        
    # 2. Process dense list (1-indexed rank)
    for rank, hit in enumerate(dense_hits, start=1):
        doc_id = hit["id"]
        doc_map[doc_id] = hit
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
        
    # 3. Sort by fused score descending
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    
    fused_results = []
    for doc_id in sorted_ids:
        doc = doc_map[doc_id]
        fused_results.append({
            "id": doc["id"],
            "chapter": doc["chapter"],
            "text": doc["text"],
            "fused_score": scores[doc_id]
        })
        
    return fused_results
