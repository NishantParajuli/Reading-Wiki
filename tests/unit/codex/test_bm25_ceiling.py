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
