import numpy as np

from novelwiki.modules.codex.adapters.outbound.retrieval.bm25 import BM25Manager


def _manager(corpus: list[dict]) -> BM25Manager:
    manager = BM25Manager(1)
    manager.corpus = corpus
    manager.chapter_arr = np.array([row["chapter"] for row in corpus], dtype=float)
    manager._build_retriever()
    return manager


def test_future_documents_cannot_change_earlier_ceiling_bm25_ranking():
    visible = [
        {"id": 1, "chapter": 1.0, "text": "red gem promise and journey"},
        {"id": 2, "chapter": 2.0, "text": "red promise at the academy"},
    ]
    future = [
        {"id": 100 + index, "chapter": 99.0, "text": "red gem " * (index + 1)}
        for index in range(12)
    ]

    before = _manager(visible).search("red gem promise", 2.0, k=2)
    after = _manager([*visible, *future]).search("red gem promise", 2.0, k=2)

    assert [hit["id"] for hit in after] == [hit["id"] for hit in before]
    assert [hit["score"] for hit in after] == [hit["score"] for hit in before]


def test_equivalent_numeric_ceilings_reuse_the_same_prefix_index():
    manager = _manager([
        {"id": 1, "chapter": 1.0, "text": "first chapter"},
        {"id": 2, "chapter": 500.0, "text": "second chapter"},
        {"id": 3, "chapter": 501.0, "text": "third chapter"},
        {"id": 4, "chapter": 502.0, "text": "fourth chapter"},
    ])

    first, first_eligible = manager._retriever_for_ceiling(500.1)
    equivalent, equivalent_eligible = manager._retriever_for_ceiling(500.2)
    expanded, expanded_eligible = manager._retriever_for_ceiling(501.0)

    assert first is equivalent
    assert first is not expanded
    assert np.array_equal(first_eligible, equivalent_eligible)
    assert len(first_eligible) == 2
    assert len(expanded_eligible) == 3
    assert list(manager._prefix_retrievers) == [2, 3]
