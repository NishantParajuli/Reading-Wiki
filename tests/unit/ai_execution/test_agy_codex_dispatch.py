from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_agy_codex_dispatch_forwards_preflight_to_codex(monkeypatch):
    from novelwiki.bootstrap.workers import build_agy_worker_registry
    from novelwiki.modules.codex.adapters.outbound import agy as codex_agy

    job = {"id": 17, "novel_id": 23}
    preflight = object()
    calls = []

    async def execute(job_arg, preflight_arg):
        calls.append((job_arg, preflight_arg))
        return {"done": 1}

    async def no_op(*_args, **_kwargs):
        return None

    class Index:
        async def rebuild(self):
            return None

    monkeypatch.setattr(codex_agy, "execute_codex_job", execute)
    monkeypatch.setattr(
        "novelwiki.modules.codex.adapters.outbound.ingest.chunk.chunk_all_chapters",
        no_op,
    )
    monkeypatch.setattr(
        "novelwiki.modules.codex.adapters.outbound.ingest.embed.embed_missing_chunks",
        no_op,
    )
    monkeypatch.setattr(
        "novelwiki.modules.codex.adapters.outbound.retrieval.bm25.get_bm25_manager",
        lambda _novel_id: Index(),
    )

    class Context:
        async def bail_if_canceled(self, _job_id):
            return None

        async def set_progress(self, *_args, **_kwargs):
            return None

    handler = build_agy_worker_registry().resolve("codex_build")
    assert await handler(job, preflight, Context()) == {"step": 4, "steps": 4, "done": 1}
    assert calls == [(job, preflight)]


@pytest.mark.asyncio
async def test_agy_codex_retry_reuses_chunks_and_embeddings():
    from novelwiki.modules.codex.adapters.inbound.jobs import execute_agy_codex_job

    calls = []

    class Context:
        async def bail_if_canceled(self, job_id):
            calls.append(("cancel", job_id))

        async def set_progress(self, *_args, **_kwargs):
            return None

        async def chunk_all_chapters(self, novel_id, **kwargs):
            calls.append(("chunk", novel_id, kwargs))

        async def embed_missing_chunks(self, novel_id, **kwargs):
            calls.append(("embed", novel_id, kwargs))

        async def execute_codex_job(self, _job, _preflight):
            calls.append(("extract",))
            return {"chapters": 5, "checkpointed_chapters": 1}

        async def rebuild_bm25(self, novel_id):
            calls.append(("index", novel_id))

    job = {
        "id": 10,
        "novel_id": 33,
        "attempts": 2,
        "options": {"force": True, "from_chapter": 1, "to_chapter": 5},
    }
    result = await execute_agy_codex_job(job, object(), Context())
    assert [call[0] for call in calls].count("chunk") == 0
    assert [call[0] for call in calls].count("embed") == 0
    assert result["checkpointed_chapters"] == 1
