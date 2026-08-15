from __future__ import annotations

from types import SimpleNamespace

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
async def test_agy_codex_retry_reruns_idempotent_preprocessing():
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
    chunk_call = next(call for call in calls if call[0] == "chunk")
    embed_call = next(call for call in calls if call[0] == "embed")
    assert chunk_call[1] == 33
    assert {key: value for key, value in chunk_call[2].items() if key != "cancel_check"} == {
        "force": True,
        "from_chapter": 1,
        "to_chapter": 5,
    }
    assert callable(chunk_call[2]["cancel_check"])
    assert embed_call[1] == 33
    assert {key: value for key, value in embed_call[2].items() if key != "cancel_check"} == {
        "from_chapter": 1,
        "to_chapter": 5,
    }
    assert callable(embed_call[2]["cancel_check"])
    assert result["checkpointed_chapters"] == 1


@pytest.mark.asyncio
async def test_codex_retry_progress_uses_durable_position_and_source_chapter(monkeypatch):
    from novelwiki.modules.codex.adapters.outbound import agy
    from novelwiki.modules.codex.adapters.outbound import maintenance

    progress = []
    extracted = []

    async def chapters(*_args):
        return [3.0, 4.0, 5.0]

    async def resumed(*_args):
        return {3.0}

    async def checkpointed(*_args):
        return {4.0}

    async def extract(_job, chapter, _preflight, _runtime):
        extracted.append(chapter)

    async def prune(_novel_id):
        return 0

    class Work:
        async def set_progress(self, job_id, payload, stage=None):
            progress.append((job_id, payload, stage))

        async def is_canceled(self, _job_id):
            return False

    monkeypatch.setattr(agy, "_chapters", chapters)
    monkeypatch.setattr(agy, "_resume_ready_commits", resumed)
    monkeypatch.setattr(agy, "_checkpointed_job_chapters", checkpointed)
    monkeypatch.setattr(agy, "_extract_chapter", extract)
    monkeypatch.setattr(maintenance, "prune_orphan_entities", prune)
    runtime = SimpleNamespace(
        work=Work(),
        ai=SimpleNamespace(provider_label="OpenAI Codex"),
    )

    result = await agy.execute_codex_job(
        {"id": 42, "novel_id": 7, "options": {}}, object(), runtime=runtime,
    )

    assert extracted == [5.0]
    active = progress[1]
    assert active[1]["done"] == 2
    assert active[1]["total"] == 3
    assert active[1]["current_chapter"] == 5.0
    assert active[1]["stage"] == "extracting OpenAI Codex source chapter 5 (3/3)"
    assert active[2] == active[1]["stage"]
    assert result["chapters"] == 3
