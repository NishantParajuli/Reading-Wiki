"""Provider-free contracts for automatic art direction and bounded continuity."""
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from novelwiki.modules.codex.application.illustration_worker import IllustrationWorker
from novelwiki.modules.codex.adapters.outbound.illustration_store import IllustrationStore
from novelwiki.modules.codex.domain.illustrations import (
    IllustrationPlan, placement_metadata, source_hash, validate_plan,
)
from novelwiki.modules.reading.adapters.outbound.codex import PostgresReadingCodexGateway

TEXT = "The morning mist lifted from the harbor.\n\nA bronze bell rang above the empty square."


def planned(count=1, placement=None):
    return {
        "characters": [], "name_updates": [],
        "scenes": [{
            "title": f"Harbor {index}", "caption": "Morning over the harbor.",
            "evidence": "The morning mist lifted from the harbor.",
            "characters": [], "prompt": "A luminous anime harbor under warm dawn light. " * 3,
            "placement": placement or {"position": "start", "anchor": ""},
        } for index in range(count)],
    }


def harness(*, count=None, decision=None, planned_count=2):
    snapshot = {"title": "Harbor", "content": TEXT}
    saved, images = {}, []

    async def save_plan(_job, value):
        saved.update(deepcopy(value))
        return saved

    async def save(**kwargs):
        images.append(kwargs)
        return kwargs

    store = SimpleNamespace(
        plan=AsyncMock(side_effect=lambda _: saved or None),
        save_plan=AsyncMock(side_effect=save_plan), references=AsyncMock(return_value=[]),
        context=AsyncMock(return_value={"previous_chapters": [{"chapter": 1, "text": "Older."}]}),
        for_job=AsyncMock(side_effect=lambda _: images), save=AsyncMock(side_effect=save),
    )
    renderer = SimpleNamespace(
        plan=AsyncMock(side_effect=[decision or {"previous_chapters": 0, "max_chars": 0, "reason": "Self contained."}, planned(planned_count)]),
        image=AsyncMock(return_value=b"png"),
    )
    preceding = AsyncMock(return_value=[{"chapter": 1, "text": "Older."}])
    worker = IllustrationWorker(
        store=store, snapshot=AsyncMock(return_value=snapshot), renderer=renderer,
        progress=AsyncMock(), cancel=AsyncMock(), preceding=preceding,
    )
    job = {"id": 12, "novel_id": 1, "options": {
        "chapter": 2, "style": "luminous", "count": count, "source_hash": source_hash(snapshot),
    }}
    return worker, job, saved, images, preceding


@pytest.mark.asyncio
async def test_auto_count_first_checks_current_text_without_retrieving_history():
    worker, job, saved, images, preceding = harness()
    result = await worker.execute(job)
    assert result["images"] == 2
    first = worker.renderer.plan.call_args_list[0].args[1]
    assert set(first) == {"chapter", "title", "text", "length"}
    assert first["text"] == TEXT
    preceding.assert_not_awaited()
    worker.store.context.assert_not_awaited()
    assert worker.renderer.plan.call_args_list[1].args[1]["scene_count"] is None
    assert saved["context"] == {"previous_chapters": []}
    assert [row["metadata"]["count"] for row in images] == [2, 2]
    assert images[0]["metadata"]["placement"] == {"position": "start", "anchor": "", "offset": 0}


@pytest.mark.asyncio
async def test_selected_context_is_fetched_only_after_decision_and_saved_for_retry():
    decision = {"previous_chapters": 1, "max_chars": 1800, "reason": "Continuation."}
    worker, job, saved, images, preceding = harness(decision=decision)
    worker.renderer.image.side_effect = [RuntimeError("provider temporarily unavailable"), b"png", b"png"]
    with pytest.raises(RuntimeError):
        await worker.execute(job)
    assert saved["context_decision"] == decision
    preceding.assert_awaited_once_with(1, 2, 1, 1800)
    assert worker.renderer.plan.await_count == 2
    await worker.execute(job)
    assert worker.renderer.plan.await_count == 2
    assert preceding.await_count == 1
    assert len(images) == 2


@pytest.mark.asyncio
async def test_fixed_count_existing_jobs_still_enforced():
    worker, job, *_ = harness(count=1, planned_count=2)
    with pytest.raises(ValueError, match="requested image count"):
        await worker.execute(job)
    worker.renderer.image.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("chapters,budget", [(0, 2000), (1, 0), (4, 2000), (2, 9001)])
async def test_invalid_context_budget_never_reads_prior_text(chapters, budget):
    worker, job, _, _, preceding = harness(decision={"previous_chapters": chapters, "max_chars": budget, "reason": "Test"})
    with pytest.raises(ValueError):
        await worker.execute(job)
    preceding.assert_not_awaited()


@pytest.mark.parametrize("position,anchor,offset", [
    ("start", "", 0), ("end", "", len(TEXT)),
    ("after", "The morning mist lifted from the harbor.", len("The morning mist lifted from the harbor.")),
])
def test_scene_placement_exact_offsets(position, anchor, offset):
    plan = IllustrationPlan.model_validate(planned(placement={"position": position, "anchor": anchor}))
    validate_plan(plan, TEXT, None, set())
    assert placement_metadata(plan.scenes[0], TEXT)["offset"] == offset


@pytest.mark.parametrize("placement,content", [
    ({"position": "after", "anchor": "A place absent from this chapter."}, TEXT),
    ({"position": "after", "anchor": "The morning mist lifted from the harbor."}, TEXT + TEXT),
    ({"position": "start", "anchor": "This should be empty"}, TEXT),
])
def test_invalid_or_ambiguous_anchors_rejected(placement, content):
    plan = IllustrationPlan.model_validate(planned(placement=placement))
    with pytest.raises(ValueError, match="placement"):
        validate_plan(plan, content, None, set())


def test_legacy_plan_uses_evidence_anchor_or_end_when_ambiguous():
    data = planned()
    del data["scenes"][0]["placement"]
    scene = IllustrationPlan.model_validate(data).scenes[0]
    assert placement_metadata(scene, TEXT)["position"] == "after"
    assert placement_metadata(scene, TEXT + TEXT)["position"] == "end"


class Pool:
    def __init__(self, rows):
        self.connection = SimpleNamespace(fetch=AsyncMock(return_value=rows))

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


@pytest.mark.asyncio
async def test_context_prefers_matching_summaries_and_bounds_total_text():
    pool = Pool([{"chapter": 8, "summary": "S" * 10000}])
    store = IllustrationStore(pool)
    result = await store.context(1, 10, preceding=[
        {"chapter": 9, "title": "Nine", "text": "T" * 10000},
        {"chapter": 8, "title": "Eight", "text": "Unused"},
        {"chapter": 10, "title": "Current", "text": "Must not appear"},
        {"chapter": 11, "title": "Future", "text": "Must not appear"},
    ], max_chars=3000)
    chapters = result["previous_chapters"]
    assert [row["chapter"] for row in chapters] == [8, 9]
    assert [row["kind"] for row in chapters] == ["summary", "chapter_tail"]
    assert sum(len(row["text"]) for row in chapters) == 3000
    assert pool.connection.fetch.call_args.args[2] == [9.0, 8.0]


@pytest.mark.asyncio
async def test_reading_gateway_fetches_only_previous_narrative_tails():
    pool = Pool([])
    gateway = PostgresReadingCodexGateway(pool)
    await gateway.previous_illustration_context(1, 25, 3, 9000)
    query, *args = pool.connection.fetch.call_args.args
    assert "number<$2" in query and "right(content,$4)" in query
    assert args == [1, 25, 3, 3000, ["chapter", "interlude"]]
    pool.connection.fetch.reset_mock()
    assert await gateway.previous_illustration_context(1, 25, 0, 0) == []
    pool.connection.fetch.assert_not_awaited()


def context_with_provenance(worker):
    previous = {"title": "Previous chapter", "content": "The travelers approached the harbor."}
    current = {"title": "Harbor", "content": TEXT}
    sources = [{"chapter": 1.0, "source_hash": source_hash(previous)}]
    worker.store.context.return_value = {"previous_chapters": [{
        **sources[0], "title": previous["title"], "text": previous["content"],
        "kind": "chapter_tail",
    }]}
    worker.snapshot.side_effect = lambda novel, chapter: previous if chapter == 1 else current
    return previous, sources


@pytest.mark.asyncio
async def test_prior_context_changed_during_render_does_not_publish_image():
    from novelwiki.modules.codex.application.illustrations import IllustrationSourceChanged

    worker, job, _, images, _ = harness(decision={
        "previous_chapters": 1, "max_chars": 2000, "reason": "Continuation.",
    })
    previous, _ = context_with_provenance(worker)

    async def image(*_):
        previous["content"] = "The source was edited while the provider was painting."
        return b"png"

    worker.renderer.image.side_effect = image
    with pytest.raises(IllustrationSourceChanged, match="preceding chapter"):
        await worker.execute(job)
    assert images == []
    worker.store.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_prior_context_changed_before_retry_rejects_saved_plan():
    from novelwiki.modules.codex.application.illustrations import IllustrationSourceChanged

    worker, job, saved, _, _ = harness(decision={
        "previous_chapters": 1, "max_chars": 2000, "reason": "Continuation.",
    })
    previous, sources = context_with_provenance(worker)
    worker.renderer.image.side_effect = RuntimeError("provider unavailable")
    with pytest.raises(RuntimeError):
        await worker.execute(job)
    assert saved["context"]["previous_chapters"][0]["source_hash"] == sources[0]["source_hash"]
    previous["title"] = "A corrected title"
    with pytest.raises(IllustrationSourceChanged, match="preceding chapter"):
        await worker.execute(job)
    assert worker.renderer.plan.await_count == 2
    assert worker.renderer.image.await_count == 1


@pytest.mark.asyncio
async def test_published_scene_retains_previous_context_provenance():
    worker, job, _, images, _ = harness(decision={
        "previous_chapters": 1, "max_chars": 2000, "reason": "Continuation.",
    })
    _, sources = context_with_provenance(worker)
    await worker.execute(job)
    assert all(row["metadata"]["sources"] == sources for row in images)
