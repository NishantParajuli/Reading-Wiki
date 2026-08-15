import logging
from novelwiki.platform.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def reciprocal_rank_fusion(
    sparse_hits: list[dict], 
    dense_hits: list[dict], 
    rrf_k: int | None = None,
    *,
    result_limit: int | None = None,
    source_quota_ratio: float | None = None,
) -> list[dict]:
    """
    Fuses sparse and dense hits lists using Reciprocal Rank Fusion (RRF).
    Scores docs as: sum(1 / (rrf_k + rank))
    Returns list sorted by score descending.
    """
    if rrf_k is None:
        rrf_k = settings.RRF_K
        
    scores = {}  # chunk_id -> fused_score
    best_rank = {}
    doc_map = {} # chunk_id -> document metadata
    
    # 1. Process sparse list (1-indexed rank)
    for rank, hit in enumerate(sparse_hits, start=1):
        doc_id = hit["id"]
        doc_map[doc_id] = hit
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
        best_rank[doc_id] = min(rank, best_rank.get(doc_id, rank))
        
    # 2. Process dense list (1-indexed rank)
    for rank, hit in enumerate(dense_hits, start=1):
        doc_id = hit["id"]
        doc_map[doc_id] = hit
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
        best_rank[doc_id] = min(rank, best_rank.get(doc_id, rank))
        
    # 3. Sort by fused score descending
    sorted_ids = sorted(
        scores, key=lambda doc_id: (-scores[doc_id], best_rank[doc_id], doc_id)
    )
    if result_limit is not None:
        ratio = (
            settings.RRF_SOURCE_QUOTA_RATIO
            if source_quota_ratio is None else source_quota_ratio
        )
        quota = min(result_limit, max(1, round(result_limit * ratio)))
        required = {
            hit["id"] for hit in sparse_hits[:quota]
        } | {
            hit["id"] for hit in dense_hits[:quota]
        }
        selected = [doc_id for doc_id in sorted_ids if doc_id in required]
        selected.extend(
            doc_id for doc_id in sorted_ids
            if doc_id not in required and len(selected) < result_limit
        )
        sorted_ids = sorted(selected[:result_limit], key=lambda doc_id: (
            -scores[doc_id], best_rank[doc_id], doc_id
        ))
    
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
