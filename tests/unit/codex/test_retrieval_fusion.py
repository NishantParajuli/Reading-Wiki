from novelwiki.modules.codex.adapters.outbound.retrieval.fuse import (
    reciprocal_rank_fusion,
)


def _hit(chunk_id: int) -> dict:
    return {"id": chunk_id, "chapter": float(chunk_id), "text": f"chunk {chunk_id}"}


def test_fusion_reserves_candidates_from_both_retrievers():
    sparse = [_hit(chunk_id) for chunk_id in range(1, 51)]
    dense = [_hit(chunk_id) for chunk_id in range(100, 150)]

    fused = reciprocal_rank_fusion(
        sparse,
        dense,
        result_limit=20,
        source_quota_ratio=0.4,
    )
    ids = {hit["id"] for hit in fused}

    assert len(fused) == 20
    assert {hit["id"] for hit in sparse[:8]} <= ids
    assert {hit["id"] for hit in dense[:8]} <= ids


def test_fusion_is_deterministic_for_equal_rank_scores():
    first = reciprocal_rank_fusion([_hit(2)], [_hit(1)])
    second = reciprocal_rank_fusion([_hit(2)], [_hit(1)])

    assert [hit["id"] for hit in first] == [1, 2]
    assert first == second
