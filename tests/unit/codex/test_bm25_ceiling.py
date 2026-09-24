import asyncio
import threading

import numpy as np
import pytest

from novelwiki.modules.codex.adapters.outbound.retrieval.bm25 import BM25Manager
from novelwiki.platform.config import settings


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


@pytest.mark.parametrize("field,replacement", [("text", "blue gem"), ("chapter", 2.0)])
def test_persisted_index_rejects_source_changes_with_stable_ids(tmp_path, field, replacement):
    manager = _manager([{"id": 1, "chapter": 1.0, "text": "gold gem"}])
    manager.index_dir = str(tmp_path)
    manager._meta_path = str(tmp_path / "novelwiki_meta.json")
    manager._save()
    assert manager._try_load_from_disk() is True

    manager.corpus[0][field] = replacement

    assert manager._try_load_from_disk() is False


@pytest.mark.asyncio
async def test_failed_index_build_is_retried_on_next_query(monkeypatch):
    manager = BM25Manager(7)
    attempts = 0

    async def load_corpus():
        manager.corpus = [{"id": 1, "chapter": 1.0, "text": "chapter"}]

    def build():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("temporary index storage failure")

    monkeypatch.setattr(manager, "_load_corpus_rows", load_corpus)
    monkeypatch.setattr(manager, "_try_load_from_disk", lambda: False)
    monkeypatch.setattr(manager, "_build_retriever", build)
    monkeypatch.setattr(manager, "_save", lambda: None)

    with pytest.raises(OSError):
        await manager.ensure_loaded()
    assert manager._loaded is False

    await manager.ensure_loaded()
    assert attempts == 2
    assert manager._loaded is True


@pytest.mark.parametrize("future", [[], [{"id": 2, "chapter": 2.0, "text": "red gem"}]])
def test_visible_corpus_without_searchable_tokens_returns_no_hits(future):
    manager = _manager([{"id": 1, "chapter": 1.0, "text": "the and or"}, *future])

    assert manager.search("red gem", 1.0) == []


@pytest.mark.asyncio
async def test_rebuild_waits_for_inflight_search_to_finish(monkeypatch):
    manager = _manager([{"id": 1, "chapter": 1.0, "text": "red gem"}])
    search_started = asyncio.Event()
    finish_search = asyncio.Event()

    async def offload(fn, *args):
        if fn == manager.search:
            search_started.set()
            await finish_search.wait()
        return fn(*args)

    async def load_new_corpus():
        manager.corpus = [{"id": 2, "chapter": 1.0, "text": "blue gem"}]
        manager.chapter_arr = np.array([1.0])
        manager._prefix_retrievers.clear()

    monkeypatch.setattr(manager, "_offload", offload)
    monkeypatch.setattr(manager, "_load_corpus_rows", load_new_corpus)
    monkeypatch.setattr(manager, "_save", lambda: None)
    search_task = asyncio.create_task(manager.asearch("red gem", 1.0))
    await search_started.wait()
    rebuild_task = asyncio.create_task(manager.rebuild())
    await asyncio.sleep(0)
    finish_search.set()
    hits, _ = await asyncio.gather(search_task, rebuild_task)

    assert [hit["id"] for hit in hits] == [1]
    assert manager.corpus[0]["id"] == 2


@pytest.mark.asyncio
async def test_cancelled_search_holds_index_until_worker_thread_finishes(monkeypatch):
    manager = BM25Manager(1)
    started = threading.Event()
    finish = threading.Event()
    rebuilt = False

    def search(*_args):
        started.set()
        assert finish.wait(3), "test did not release search worker"
        return []

    async def load_corpus():
        nonlocal rebuilt
        rebuilt = True

    monkeypatch.setattr(settings, "BM25_THREAD_OFFLOAD", True)
    monkeypatch.setattr(manager, "search", search)
    monkeypatch.setattr(manager, "_load_corpus_rows", load_corpus)
    search_task = asyncio.create_task(manager.asearch("gem", 1))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        search_task.cancel()
        rebuild_task = asyncio.create_task(manager.rebuild())
        await asyncio.sleep(0)
        search_task.cancel()
        await asyncio.sleep(0)
        rebuilt_before_search_finished = rebuilt
    finally:
        finish.set()
    with pytest.raises(asyncio.CancelledError):
        await search_task
    await rebuild_task

    assert rebuilt_before_search_finished is False
    assert rebuilt is True
