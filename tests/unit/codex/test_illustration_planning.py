"""Provider-free contracts for automatic art direction and bounded continuity."""
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from novelwiki.modules.codex.application.illustration_worker import IllustrationWorker
from novelwiki.modules.codex.adapters.outbound.illustration_store import IllustrationStore
from novelwiki.modules.codex.domain.illustrations import (
    IllustrationPlan, IllustrationPlanInvalid, placement_metadata, source_hash, validate_plan,
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
    worker.renderer.plan.side_effect = [
        {"previous_chapters": 0, "max_chars": 0, "reason": "Self contained."},
        *[planned(2) for _ in range(3)],
    ]
    with pytest.raises(IllustrationPlanInvalid, match="requested image count"):
        await worker.execute(job)
    worker.renderer.image.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("chapters,budget", [(0, 2000), (1, 0), (4, 2000), (2, 9001)])
async def test_invalid_context_budget_never_reads_prior_text(chapters, budget):
    worker, job, _, _, preceding = harness(decision={"previous_chapters": chapters, "max_chars": budget, "reason": "Test"})
    worker.renderer.plan.side_effect = None
    worker.renderer.plan.return_value = {"previous_chapters": chapters, "max_chars": budget, "reason": "Test"}
    with pytest.raises(IllustrationPlanInvalid, match="consistent count and budget"):
        await worker.execute(job)
    assert worker.renderer.plan.await_count == 3
    preceding.assert_not_awaited()
    worker.store.save_plan.assert_not_awaited()
    worker.renderer.image.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["evidence", "placement", "schema", "identity", "name"])
async def test_invalid_plan_is_repaired_before_checkpoint_or_render(failure):
    worker, job, saved, images, preceding = harness()
    invalid = planned()
    if failure == "evidence":
        invalid["scenes"][0]["evidence"] = "A paraphrase absent from the chapter."
    elif failure == "placement":
        invalid["scenes"][0]["placement"] = {"position": "after", "anchor": "An absent anchor quotation."}
    elif failure == "schema":
        invalid["scenes"][0]["prompt"] = 42
    elif failure == "identity":
        invalid["scenes"][0]["characters"] = ["missing-character"]
    else:
        invalid["name_updates"] = [{"key": "missing", "name": "New name", "aliases": [], "evidence": TEXT[:39]}]
    worker.renderer.plan.side_effect = [
        {"previous_chapters": 0, "max_chars": 0, "reason": "Self contained."},
        invalid, planned(),
    ]
    await worker.execute(job)
    assert worker.renderer.plan.await_count == 3
    correction = worker.renderer.plan.call_args_list[2].args[1]
    assert correction["text"] == TEXT
    assert correction["repair"]["previous_response"] == invalid
    assert correction["repair"]["validation_error"]
    assert saved["plan"] == planned()
    worker.store.save_plan.assert_awaited_once()
    worker.renderer.image.assert_awaited_once()
    assert len(images) == 1
    preceding.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeated_bad_evidence_is_bounded_and_has_safe_job_error():
    from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.runner import safe_error_summary

    worker, job, saved, images, _ = harness()
    invalid = planned()
    invalid["scenes"][0]["evidence"] = "Private invented chapter text."
    worker.renderer.plan.side_effect = [
        {"previous_chapters": 0, "max_chars": 0, "reason": "Self contained."},
        invalid, invalid, invalid,
    ]
    with pytest.raises(IllustrationPlanInvalid) as error:
        await worker.execute(job)
    summary = safe_error_summary(error.value)
    assert summary == (
        "illustration_plan_invalid: IllustrationPlanInvalid "
        "(Illustration scene has no exact evidence in this chapter)"
    )
    assert "Private" not in summary
    assert worker.renderer.plan.await_count == 4
    assert not saved and not images
    worker.renderer.image.assert_not_awaited()


@pytest.mark.asyncio
async def test_schema_failure_does_not_log_untrusted_values():
    import traceback

    worker, job, *_ = harness()
    worker.renderer.plan.side_effect = None
    worker.renderer.plan.return_value = {"previous_chapters": "PRIVATE CHAPTER CONTENT"}
    with pytest.raises(IllustrationPlanInvalid) as error:
        await worker.execute(job)
    assert "PRIVATE CHAPTER CONTENT" not in "".join(traceback.format_exception(error.value))


@pytest.mark.asyncio
async def test_context_can_be_corrected_before_retrieving_history():
    worker, job, saved, _, preceding = harness()
    worker.renderer.plan.side_effect = [
        {"previous_chapters": 1, "max_chars": 0, "reason": "Invalid budget."},
        {"previous_chapters": 1, "max_chars": 1800, "reason": "Continuation."},
        planned(),
    ]
    await worker.execute(job)
    preceding.assert_awaited_once_with(1, 2, 1, 1800)
    assert saved["context_decision"]["max_chars"] == 1800


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["cancel", "source"])
async def test_repair_checks_cancellation_and_source_before_another_provider_call(change):
    from novelwiki.modules.ai_execution.application.errors import AgyCanceled
    from novelwiki.modules.codex.application.illustrations import IllustrationSourceChanged

    worker, job, *_ = harness()
    invalid = planned()
    invalid["scenes"][0]["evidence"] = "A paraphrase absent from the chapter."
    worker.renderer.plan.side_effect = [
        {"previous_chapters": 0, "max_chars": 0, "reason": "Self contained."}, invalid,
    ]

    async def progress(_job, _progress, *, stage):
        if stage == "Correcting illustration plan":
            if change == "cancel":
                worker.cancel.side_effect = AgyCanceled("Canceled")
            else:
                worker.snapshot.return_value = {"title": "Edited", "content": TEXT}

    worker.progress.side_effect = progress
    with pytest.raises(AgyCanceled if change == "cancel" else IllustrationSourceChanged):
        await worker.execute(job)
    assert worker.renderer.plan.await_count == 2
    worker.store.save_plan.assert_not_awaited()
    worker.renderer.image.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_failure_is_not_a_plan_repair():
    from novelwiki.modules.ai_execution.application.errors import AgyError

    worker, job, *_ = harness()
    failure = AgyError("Unavailable", code="openai_codex_provider_unavailable")
    worker.renderer.plan.side_effect = failure
    with pytest.raises(AgyError) as error:
        await worker.execute(job)
    assert error.value is failure
    worker.renderer.plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_repaired_plan_is_checkpointed_and_reused_after_render_failure():
    worker, job, saved, images, _ = harness()
    invalid = planned()
    invalid["scenes"][0]["evidence"] = "A paraphrase absent from the chapter."
    worker.renderer.plan.side_effect = [
        {"previous_chapters": 0, "max_chars": 0, "reason": "Self contained."},
        invalid, planned(),
    ]
    worker.renderer.image.side_effect = [RuntimeError("Provider unavailable"), b"png"]
    with pytest.raises(RuntimeError):
        await worker.execute(job)
    await worker.execute(job)
    assert worker.renderer.plan.await_count == 3
    assert saved["plan"] == planned()
    assert len(images) == 1


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


@pytest.mark.asyncio
async def test_obsolete_saved_style_plan_cannot_resume_with_painterly_references():
    from novelwiki.modules.codex.application.illustrations import IllustrationSourceChanged

    worker, job, saved, images, _ = harness()
    saved.update({"plan": planned(), "references": {"mira": "legacy-sheet"}})
    with pytest.raises(IllustrationSourceChanged, match="style has been updated"):
        await worker.execute(job)
    worker.renderer.plan.assert_not_awaited()
    worker.renderer.image.assert_not_awaited()
    assert images == []


@pytest.mark.asyncio
async def test_old_luminous_reference_is_excluded_and_new_plan_and_images_are_versioned():
    from novelwiki.modules.codex.domain.illustrations import style_revision

    worker, job, saved, images, _ = harness()
    worker.store.references.return_value = [{
        "id": "legacy-sheet", "kind": "reference", "style": "luminous",
        "novel_id": 1, "chapter": 1, "character_key": "mira", "title": "Mira",
        "metadata": {}, "source_hash": job["options"]["source_hash"],
    }]
    await worker.execute(job)
    revision = style_revision("luminous")
    assert worker.store.references.call_args.kwargs == {"revision": revision}
    assert worker.renderer.plan.call_args_list[1].args[1]["existing_characters"] == []
    assert saved["style_revision"] == revision
    assert all(row["metadata"]["style_revision"] == revision for row in images)


@pytest.mark.asyncio
async def test_reference_revision_is_filtered_before_latest_and_limit():
    pool = Pool([])
    await IllustrationStore(pool).references(1, 2, "luminous", TEXT, revision="soft-cel-anime-v2")
    query, *args = pool.connection.fetch.call_args.args
    assert query.index("metadata->>'style_revision'=$5") < query.index("ORDER BY character_key")
    assert args[-1] == "soft-cel-anime-v2"
