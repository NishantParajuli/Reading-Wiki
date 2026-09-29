"""Provider-free illustration workflow regressions in a disposable PostgreSQL DB."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import novelwiki.db.connection as db_connection
from novelwiki.bootstrap.illustrations import build_illustration_service
from novelwiki.db.connection import close_db_pool, get_db_pool
from novelwiki.db.schema import init_database
from novelwiki.kernel.errors import Conflict, Forbidden, NotFound, QuotaExceeded
from novelwiki.modules.ai_execution.public import AgyCanceled
from novelwiki.modules.codex.adapters.outbound.artifacts import (
    PostgresCodexTransactionService,
)
from novelwiki.modules.codex.adapters.outbound.illustration_store import (
    IllustrationStore,
)
from novelwiki.modules.codex.adapters.outbound.maintenance import reset_structured_codex
from novelwiki.modules.codex.application.illustration_worker import IllustrationWorker
from novelwiki.modules.codex.application.illustrations import metadata
from novelwiki.modules.codex.domain.illustrations import source_hash
from novelwiki.modules.identity.public import Principal
from novelwiki.modules.reading.adapters.outbound.codex import (
    PostgresReadingCodexGateway,
)
from novelwiki.modules.work.adapters.outbound import postgres as work
from novelwiki.platform.config import settings

QUOTE = "Mira lifted the bronze lantern."
CONTENT = QUOTE + " Warm light revealed the old bridge and the quiet river below."


@pytest_asyncio.fixture()
async def art_db(monkeypatch):
    try:
        await close_db_pool()
    except RuntimeError:
        pass
    db_connection._pool = None
    monkeypatch.setattr(settings, "OPENAI_CODEX_ENABLED", True)
    monkeypatch.setattr(settings, "OPENAI_CODEX_CODEX_ENABLED", True)
    await init_database()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM novels CASCADE; DELETE FROM users CASCADE;")
        users = []
        for name in ("artowner", "artreader"):
            users.append(
                dict(
                    await conn.fetchrow(
                        "INSERT INTO users(email,username,email_verified) VALUES($1,$2,TRUE) RETURNING *;",
                        name + "@example.test",
                        name,
                    )
                )
            )
        novel = await conn.fetchval(
            "INSERT INTO novels(title,owner_id,visibility) VALUES('Art book',$1,'public') RETURNING id;",
            users[0]["id"],
        )
        for chapter in (1, 2, 3):
            await conn.execute(
                "INSERT INTO chapters(novel_id,number,title,content,language,kind) "
                "VALUES($1,$2,$3,$4,'en','chapter');",
                novel,
                chapter,
                f"Chapter {chapter}",
                CONTENT,
            )
        await conn.execute(
            "INSERT INTO reading_progress(user_id,novel_id,last_chapter,max_chapter_read) "
            "VALUES($1,$3,2,2),($2,$3,1,1);",
            users[0]["id"],
            users[1]["id"],
            novel,
        )
        await conn.execute(
            "INSERT INTO user_ai_backend_policies(user_id,openai_codex_enabled,openai_codex_workloads,"
            "max_concurrent_openai_codex_jobs) VALUES($1,TRUE,ARRAY['codex_extract'],1);",
            users[0]["id"],
        )
    fixture = SimpleNamespace(
        pool=pool,
        novel=novel,
        owner=Principal.from_user(users[0]),
        reader=Principal.from_user(users[1]),
        owner_row=users[0],
        reader_row=users[1],
        store=IllustrationStore(pool),
        snapshot=PostgresReadingCodexGateway(pool).chapter_snapshot,
    )
    fixture.service = await build_illustration_service()
    yield fixture
    await close_db_pool()
    db_connection._pool = None


class Renderer:
    def __init__(
        self, *, fail_image=None, after_image=None, after_plan=None, characters=True
    ):
        self.fail_image, self.after_image, self.after_plan = (
            fail_image,
            after_image,
            after_plan,
        )
        self.characters = characters
        self.plans, self.images = [], []

    async def plan(self, instructions, data, schema):
        if "previous_chapters" in schema.get("properties", {}):
            return {
                "previous_chapters": 0,
                "max_chars": 0,
                "reason": "Self-contained scene.",
            }
        self.plans.append(data)
        result = {
            "characters": []
            if data["existing_characters"] or not self.characters
            else [
                {
                    "key": "mira",
                    "name": "Mira",
                    "canon": "Carries a bronze lantern.",
                    "design_notes": "A cobalt coat is an artistic choice.",
                    "prompt": "A coherent character sheet with face study and a cobalt coat. "
                    * 2,
                }
            ],
            "scenes": [
                {
                    "title": f"Lantern {index + 1}",
                    "caption": "Warm light on the bridge.",
                    "evidence": QUOTE,
                    "characters": ["mira"] if self.characters else [],
                    "prompt": "Wide cinematic composition of a lantern lighting the old bridge. "
                    * 2,
                }
                for index in range(data["scene_count"] or 1)
            ],
        }
        if self.after_plan:
            await self.after_plan()
        return result

    async def image(self, prompt, references):
        self.images.append((prompt, references))
        if self.fail_image == len(self.images):
            raise RuntimeError("simulated transient rendering failure")
        if self.after_image:
            await self.after_image()
        return b"image-" + str(len(self.images)).encode()


async def enqueue(db, chapter=2.0, count=1, force=False):
    result = await db.service.generate(
        db.novel, chapter, db.owner, count=count, force=force
    )
    return await work.get_job(result["job_id"])


async def execute(db, job, renderer, cancel=None):
    worker = IllustrationWorker(
        store=db.store,
        snapshot=db.snapshot,
        renderer=renderer,
        progress=AsyncMock(),
        cancel=cancel or AsyncMock(),
    )
    return await worker.execute(job)


async def finish(job):
    await work.update_job(job["id"], status="running")
    assert await work.mark_done_if_running(
        job["id"], {"images": job["options"].get("count")}
    )


@pytest.mark.asyncio
async def test_requests_deduplicate_before_queue_limit_and_preserve_image_count(art_db):
    db = art_db
    first = await db.service.generate(db.novel, 2.0, db.owner)
    second = await db.service.generate(db.novel, 2.0, db.owner)
    assert first["created"] is True and second == {
        "job_id": first["job_id"],
        "created": False,
    }
    with pytest.raises(QuotaExceeded):
        await db.service.generate(db.novel, 2.0, db.owner, count=3)
    async with db.pool.acquire() as conn:
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM jobs WHERE kind='codex_illustrate'"
            )
            == 1
        )
    job = await work.get_job(first["job_id"])
    assert job["backend_model"] == "gpt-6-luna"
    assert (
        job["execution_backend"] == "openai_codex"
        and job["backend_fallback_allowed"] is False
    )


@pytest.mark.asyncio
async def test_owner_read_ceiling_private_access_and_readonly_gallery(art_db):
    db = art_db
    with pytest.raises(Forbidden, match="Read this chapter"):
        await db.service.generate(db.novel, 3.0, db.owner)
    with pytest.raises(Forbidden):
        await db.service.generate(db.novel, 1.0, db.reader)
    view = await db.service.list(db.novel, 1.0, db.reader)
    assert view["can_generate"] is False
    job = await enqueue(db)
    await execute(db, job, Renderer())
    row = next(
        row for row in await db.store.for_job(job["id"]) if row["kind"] == "scene"
    )
    with pytest.raises(Forbidden, match="Read this chapter"):
        await db.service.image(db.novel, row["id"], db.reader)
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE novels SET visibility='private' WHERE id=$1", db.novel
        )
    with pytest.raises(NotFound):
        await db.service.image(db.novel, row["id"], db.reader)
    with pytest.raises(NotFound):
        await db.service.image(db.novel + 1, row["id"], db.owner)


@pytest.mark.asyncio
async def test_retry_reuses_saved_plan_sheets_and_scenes_without_duplicate_charges(
    art_db,
):
    db = art_db
    job = await enqueue(db, count=2)
    failed = Renderer(fail_image=3)
    with pytest.raises(RuntimeError, match="transient"):
        await execute(db, job, failed)
    assert len(failed.plans) == 1 and len(failed.images) == 3
    assert len(await db.store.for_job(job["id"])) == 2  # sheet and scene 1
    resumed = Renderer()
    await execute(db, job, resumed)
    assert resumed.plans == [] and len(resumed.images) == 1
    assert resumed.images[0][1] == [b"image-1"]
    assert len(await db.store.for_job(job["id"])) == 3
    await finish(job)
    gallery = await db.service.list(db.novel, 2.0, db.owner)
    assert [item["title"] for item in gallery["items"] if item["kind"] == "scene"] == [
        "Lantern 1",
        "Lantern 2",
    ]
    cached = await db.service.generate(db.novel, 2.0, db.owner, count=2)
    assert cached == {"job_id": job["id"], "already_created": True}


@pytest.mark.asyncio
async def test_later_chapter_reuses_past_sheets_and_hides_art_when_reference_source_changes(
    art_db,
):
    db = art_db
    first = await enqueue(db, chapter=1.0)
    await execute(db, first, Renderer())
    await finish(first)
    second = await enqueue(db, chapter=2.0)
    renderer = Renderer()
    await execute(db, second, renderer)
    assert len(renderer.images) == 1 and renderer.images[0][1] == [b"image-1"]
    assert renderer.plans[0]["existing_characters"][0]["key"] == "mira"
    scene = (await db.store.for_job(second["id"]))[0]
    assert await db.service.image(db.novel, scene["id"], db.owner) == b"image-1"
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE chapters SET content=content || ' Edited.' WHERE novel_id=$1 AND number=1",
            db.novel,
        )
    assert (await db.service.list(db.novel, 2.0, db.owner))["items"] == []
    with pytest.raises(NotFound, match="older chapter"):
        await db.service.image(db.novel, scene["id"], db.owner)
    with pytest.raises(Conflict, match="source changed"):
        await execute(db, second, Renderer())


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["cancel", "chapter", "invalidation"])
async def test_changes_during_generation_never_publish_the_returned_image(
    art_db, change
):
    db = art_db
    job = await enqueue(db)
    canceled = False

    async def cancel(_job):
        if canceled:
            raise AgyCanceled()

    async def change_during_render():
        nonlocal canceled
        if change == "cancel":
            canceled = True
        else:
            async with db.pool.acquire() as conn:
                if change == "chapter":
                    await conn.execute(
                        "UPDATE chapters SET content=content || ' Edited.' WHERE novel_id=$1 AND number=2",
                        db.novel,
                    )
                else:
                    async with conn.transaction():
                        await PostgresCodexTransactionService(
                            conn
                        ).invalidate_chapter_range(db.novel, 1, 1)

    with pytest.raises(AgyCanceled if change == "cancel" else Conflict):
        await execute(db, job, Renderer(after_image=change_during_render), cancel)
    assert await db.store.for_job(job["id"]) == []


@pytest.mark.asyncio
async def test_spoiler_context_and_reset_include_illustration_artifacts(art_db):
    db = art_db
    async with db.pool.acquire() as conn:
        for chapter, summary in [(1, "Known bridge."), (3, "Future betrayal.")]:
            await conn.execute(
                "INSERT INTO chapter_summaries(novel_id,chapter,summary,source_sha256,pipeline_version) "
                "VALUES($1,$2,$3,$4,$5)",
                db.novel,
                chapter,
                summary,
                "0" * 64,
                settings.CODEX_PIPELINE_VERSION,
            )
        entity = await conn.fetchval(
            "INSERT INTO entities(novel_id,canonical_name,type,first_seen_chapter) "
            "VALUES($1,'Mira','character',1) RETURNING id",
            db.novel,
        )
        await conn.execute(
            "INSERT INTO entity_facts(novel_id,entity_id,chapter,content) "
            "VALUES($1,$2,1,'Carries a lantern.'),($1,$2,3,'Future identity reveal.')",
            db.novel,
            entity,
        )
    job = await enqueue(db)
    renderer = Renderer()
    await execute(db, job, renderer)
    assert "Future" not in json.dumps(renderer.plans[0]["knowledge"], default=str)
    async with db.pool.acquire() as conn:
        assert await PostgresCodexTransactionService(conn).has_chapter_artifacts(
            db.novel, (2.0,)
        )
    await reset_structured_codex(db.novel)
    assert await db.store.list(db.novel, 2.0) == []
    assert await db.store.plan(job["id"]) is None


@pytest.mark.asyncio
async def test_real_app_serves_authenticated_private_image_routes_before_spa(
    art_db, monkeypatch
):
    db = art_db
    job = await enqueue(db)
    await execute(db, job, Renderer())
    row = next(
        row for row in await db.store.for_job(job["id"]) if row["kind"] == "scene"
    )
    from novelwiki.api.app import app
    from novelwiki.platform.auth import current_user
    from novelwiki.modules.codex.adapters.inbound.illustrations_http import (
        illustration_service_dependency,
    )

    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: db.owner_row)
    monkeypatch.setitem(
        app.dependency_overrides, illustration_service_dependency, lambda: db.service
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        gallery = await client.get(f"/api/novels/{db.novel}/chapters/2/illustrations")
        image = await client.get(
            f"/api/novels/{db.novel}/illustrations/{row['id']}/image"
        )
    assert gallery.status_code == 200 and gallery.headers["content-type"].startswith(
        "application/json"
    )
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"] == "private, no-store"
    assert image.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_future_character_sheets_are_never_reused_for_earlier_chapters(art_db):
    db = art_db
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE reading_progress SET max_chapter_read=3 WHERE user_id=$1",
            db.owner.user_id,
        )
    future = await enqueue(db, chapter=3.0)
    await execute(db, future, Renderer())
    await finish(future)
    earlier = await enqueue(db, chapter=2.0)
    renderer = Renderer()
    await execute(db, earlier, renderer)
    assert renderer.plans[0]["existing_characters"] == []
    assert len(renderer.images) == 2  # a new sheet, then the earlier scene
    earlier_rows = await db.store.for_job(earlier["id"])
    future_ids = {str(row["id"]) for row in await db.store.for_job(future["id"])}
    earlier_scene = next(row for row in earlier_rows if row["kind"] == "scene")
    assert not future_ids.intersection(
        json.loads(earlier_scene["metadata"])["references"]
    )


@pytest.mark.asyncio
async def test_cancel_during_planning_does_not_persist_plan_or_start_image_generation(
    art_db,
):
    db = art_db
    job = await enqueue(db)
    canceled = False

    async def cancel(_job):
        if canceled:
            raise AgyCanceled()

    async def canceled_after_plan():
        nonlocal canceled
        canceled = True

    renderer = Renderer(after_plan=canceled_after_plan)
    with pytest.raises(AgyCanceled):
        await execute(db, job, renderer, cancel)
    assert renderer.images == []
    assert await db.store.plan(job["id"]) is None


@pytest.mark.asyncio
async def test_reference_edit_during_scene_render_discards_stale_result(art_db):
    db = art_db
    reference_job = await enqueue(db, chapter=1.0)
    await execute(db, reference_job, Renderer())
    await finish(reference_job)
    job = await enqueue(db, chapter=2.0)

    async def edit_reference_source():
        async with db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE chapters SET content=content || ' Edited.' WHERE novel_id=$1 AND number=1",
                db.novel,
            )

    with pytest.raises(Conflict, match="sheet source changed"):
        await execute(db, job, Renderer(after_image=edit_reference_source))
    assert await db.store.for_job(job["id"]) == []


@pytest.mark.asyncio
async def test_changed_chapter_is_rejected_before_any_provider_call(art_db):
    db = art_db
    job = await enqueue(db)
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE chapters SET content=content || ' Edited.' WHERE novel_id=$1 AND number=2",
            db.novel,
        )
    renderer = Renderer()
    with pytest.raises(Conflict, match="Chapter changed"):
        await execute(db, job, renderer)
    assert renderer.plans == [] and renderer.images == []


@pytest.mark.asyncio
async def test_unverified_owner_cannot_generate_even_with_provider_grant(art_db):
    db = art_db
    owner = Principal(user_id=db.owner.user_id, role="user", email_verified=False)
    with pytest.raises(Forbidden, match="Verify your email"):
        await db.service.generate(db.novel, 2.0, owner)


@pytest.mark.asyncio
async def test_recurring_character_survives_large_reference_history_without_loading_images(
    art_db,
):
    import uuid

    db = art_db
    first = await enqueue(db, chapter=1.0)
    await execute(db, first, Renderer())
    await finish(first)
    digest = source_hash(await db.snapshot(db.novel, 1.0))
    async with db.pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO codex_art(id,novel_id,chapter,kind,character_key,title,style,source_hash,metadata,image,slot) "
            "VALUES($1,$2,1,'reference',$3,$4,'luminous',$5,'{}',$6,'seed')",
            [
                (
                    uuid.uuid4(),
                    db.novel,
                    f"person-{index}",
                    f"Person {index}",
                    digest,
                    b"large-reference",
                )
                for index in range(125)
            ]
            + [
                (uuid.uuid4(), db.novel, "person-0", "Person 0", digest, b"revision")
                for _ in range(20)
            ],
        )
    references = await db.store.references(db.novel, 2.0, "luminous", CONTENT)
    assert len(references) == len({row["character_key"] for row in references}) == 100
    assert references[0]["character_key"] == "mira"
    assert all("image" not in row for row in references)
    assert "image" not in await db.store.get(
        db.novel, references[0]["id"], images=False
    )
    job = await enqueue(db, chapter=2.0)
    renderer = Renderer()
    await execute(db, job, renderer)
    assert len(renderer.images) == 1
    assert renderer.images[0][1] == [b"image-1"]


@pytest.mark.asyncio
async def test_gallery_dependency_validation_fetches_reference_metadata_only(
    art_db, monkeypatch
):
    db = art_db
    job = await enqueue(db)
    await execute(db, job, Renderer())
    calls = []
    original = db.service.store.get

    async def get(novel_id, art_id, *, images=True):
        calls.append(images)
        return await original(novel_id, art_id, images=images)

    monkeypatch.setattr(db.service.store, "get", get)
    gallery = await db.service.list(db.novel, 2.0, db.owner)
    assert len(gallery["items"]) == 2
    assert calls and not any(calls)


@pytest.mark.asyncio
async def test_invalidated_plan_cannot_publish_a_late_provider_result(art_db):
    db = art_db
    job = await enqueue(db)
    await execute(db, job, Renderer())
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await PostgresCodexTransactionService(conn).invalidate_chapter_range(
                db.novel, 2, 2
            )
    with pytest.raises(Conflict, match="invalidated"):
        await db.store.save(
            novel_id=db.novel,
            chapter=2,
            kind="scene",
            key=None,
            title="Late image",
            caption="",
            style="luminous",
            source_hash=job["options"]["source_hash"],
            metadata={},
            image=b"late-result",
            job_id=job["id"],
            slot="scene:0",
        )
    assert await db.store.for_job(job["id"]) == []


RENAMING = "Mira lifted the bronze lantern. Mira now called herself Aria, also known as Starling."


class RenamingRenderer(Renderer):
    async def plan(self, instructions, data, schema):
        plan = await super().plan(instructions, data, schema)
        if "scenes" not in plan:
            return plan
        plan["name_updates"] = [
            {
                "key": "mira",
                "name": "Aria",
                "aliases": ["Starling"],
                "evidence": "Mira now called herself Aria, also known as Starling.",
            }
        ]
        return plan


async def prepare_rename(db):
    first = await enqueue(db, chapter=1.0)
    await execute(db, first, Renderer())
    await finish(first)
    original = next(
        row for row in await db.store.for_job(first["id"]) if row["kind"] == "reference"
    )
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE chapters SET content=$2 WHERE novel_id=$1 AND number=2",
            db.novel,
            RENAMING,
        )
    return original, await enqueue(db, chapter=2.0)


@pytest.mark.asyncio
async def test_name_change_keeps_pixels_aliases_and_spoiler_boundary_on_retry(art_db):
    db = art_db
    original, job = await prepare_rename(db)
    failing = RenamingRenderer(fail_image=1)
    with pytest.raises(RuntimeError, match="transient"):
        await execute(db, job, failing)
    revision = (await db.store.for_job(job["id"]))[0]
    assert revision["title"] == "Aria" and revision["character_key"] == "mira"
    assert revision["slot"] == "name:mira"
    assert json.loads(revision["metadata"])["aliases"] == ["Mira", "Starling"]
    retry = Renderer()
    await execute(db, job, retry)
    assert retry.plans == []
    assert len(retry.images) == 1 and retry.images[0][1] == [b"image-1"]
    assert "Reference image 1: Aria" in retry.images[0][0]
    assert len(await db.store.for_job(job["id"])) == 2
    for chapter, expected in ((1, "Mira"), (2, "Aria")):
        refs = await db.store.references(
            db.novel, chapter, "luminous", "Starling spoke."
        )
        assert refs[0]["title"] == expected
        gallery = await db.service.list(db.novel, chapter, db.owner)
        assert [
            item["title"] for item in gallery["items"] if item["kind"] == "reference"
        ] == [expected]
    assert (await db.store.get(db.novel, original["id"]))["title"] == "Mira"
    # Generating an earlier chapter later must not roll the preferred name back.
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE codex_art SET created_at=now()+interval '1 day' WHERE id=$1",
            original["id"],
        )
    async with db.pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO codex_art(id,novel_id,chapter,kind,character_key,title,caption,style,"
            "source_hash,metadata,image,slot,created_at) "
            "SELECT gen_random_uuid(),novel_id,chapter,kind,character_key,title,caption,style,"
            "source_hash,metadata,image,'old-revision',now()+interval '1 day' "
            "FROM codex_art CROSS JOIN generate_series(1,125) WHERE id=$1",
            original["id"],
        )
    assert (await db.store.references(db.novel, 2, "luminous", "Aria"))[0][
        "title"
    ] == "Aria"
    gallery = await db.service.list(db.novel, 2, db.owner)
    assert [
        item["title"] for item in gallery["items"] if item["kind"] == "reference"
    ] == ["Aria"]


@pytest.mark.asyncio
async def test_renamed_reference_retains_original_source_validation(art_db):
    db = art_db
    _original, job = await prepare_rename(db)
    await execute(db, job, RenamingRenderer())
    rows = await db.store.for_job(job["id"])
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE chapters SET content=content || ' Changed.' WHERE novel_id=$1 AND number=1",
            db.novel,
        )
    assert (await db.service.list(db.novel, 2, db.owner))["items"] == []
    for row in rows:
        with pytest.raises(NotFound, match="older chapter"):
            await db.service.image(db.novel, row["id"], db.owner)
    with pytest.raises(Conflict, match="sheet source changed"):
        await execute(db, job, Renderer())


@pytest.mark.asyncio
async def test_alias_matching_prioritizes_old_identity_in_large_cast(art_db):
    import uuid

    db = art_db
    _original, job = await prepare_rename(db)
    await execute(db, job, RenamingRenderer())
    digest = source_hash(await db.snapshot(db.novel, 1))
    async with db.pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO codex_art(id,novel_id,chapter,kind,character_key,title,style,source_hash,image,slot) "
            "VALUES($1,$2,1,'reference',$3,$4,'luminous',$5,$6,'seed')",
            [
                (uuid.uuid4(), db.novel, f"person-{i}", f"Person {i}", digest, b"image")
                for i in range(125)
            ],
        )
    gallery = await db.service.list(db.novel, 2, db.owner)
    assert any(item["kind"] == "scene" for item in gallery["items"])
    for name in ("Mira", "Aria", "Starling", "STARLING"):
        refs = await db.store.references(db.novel, 2, "luminous", name + " spoke.")
        assert len(refs) == 100
        assert refs[0]["character_key"] == "mira" and refs[0]["title"] == "Aria"
        assert all("image" not in ref for ref in refs)


async def execute_range(db, job, renderer, cancel=None):
    from novelwiki.modules.codex.application.illustration_batch import (
        IllustrationBatchWorker,
    )
    from novelwiki.modules.codex.adapters.outbound.illustration_range_store import (
        IllustrationRangeStore,
    )

    async def chapter(child, progress):
        return await IllustrationWorker(
            store=IllustrationRangeStore(db.pool, child["options"]["chapter"]),
            snapshot=db.snapshot,
            renderer=renderer,
            progress=progress,
            cancel=cancel or AsyncMock(),
        ).execute(child)

    return await IllustrationBatchWorker(
        store=db.store,
        snapshot=db.snapshot,
        current_rows=db.service.current_rows,
        execute_chapter=chapter,
        progress=AsyncMock(),
        cancel=cancel or AsyncMock(),
    ).execute(job)


@pytest.mark.asyncio
async def test_range_generation_ahead_is_one_job_and_preserves_read_ceiling(art_db):
    db = art_db
    result = await db.service.generate_range(
        db.novel, db.owner, from_chapter=1, to_chapter=3
    )
    assert result["chapter_count"] == 3
    repeated = await db.service.generate_range(
        db.novel, db.owner, from_chapter=1, to_chapter=3
    )
    assert repeated["job_id"] == result["job_id"] and repeated["created"] is False
    job = await work.get_job(result["job_id"])
    renderer = Renderer()
    progress = await execute_range(db, job, renderer)
    assert progress["done"] == progress["total"] == 3
    assert len(renderer.images) == 4  # one sheet, then three scenes
    assert all(len(references) == 1 for _, references in renderer.images[1:])
    rows = await db.store.for_job(job["id"])
    assert {row["slot"] for row in rows} == {
        "chapter:1:reference:mira",
        "chapter:1:scene:0",
        "chapter:2:scene:0",
        "chapter:3:scene:0",
    }
    parent = await db.store.plan(job["id"])
    assert parent["mode"] == "range"
    assert all([await db.store.range_plan(job["id"], chapter) for chapter in (1, 2, 3)])
    scene3 = next(row for row in rows if row["slot"] == "chapter:3:scene:0")
    with pytest.raises(Forbidden):
        await db.service.image(db.novel, scene3["id"], db.owner)
    with pytest.raises(Forbidden):
        await db.service.generate_range(
            db.novel, db.reader, from_chapter=1, to_chapter=3
        )
    assert (await db.service.range_info(db.novel, db.owner))["active_job"]["id"] == job[
        "id"
    ]
    assert (await db.service.list(db.novel, 2, db.owner))["active_job"]["id"] == job[
        "id"
    ]
    gallery = await db.service.list(db.novel, 2, db.owner)
    scene = next(item for item in gallery["items"] if item["kind"] == "scene")
    assert scene["placement"]["position"] == "after"
    assert scene["placement"]["anchor"] == QUOTE
    await finish(job)
    assert (await db.service.range_info(db.novel, db.owner))["active_job"][
        "status"
    ] == "done"


@pytest.mark.asyncio
async def test_range_repairs_bad_evidence_and_reuses_completed_art_on_resume(art_db):
    db = art_db

    class RepairRenderer(Renderer):
        async def plan(self, instructions, data, schema):
            result = await super().plan(instructions, data, schema)
            if "scenes" in result and data["chapter"] == 3 and "repair" not in data:
                result["scenes"][0]["evidence"] = "An invented quotation absent from this chapter."
            return result

    result = await db.service.generate_range(
        db.novel, db.owner, from_chapter=1, to_chapter=3
    )
    job = await work.get_job(result["job_id"])
    renderer = RepairRenderer()
    progress = await execute_range(db, job, renderer)
    assert progress["done"] == 3
    assert [plan["chapter"] for plan in renderer.plans] == [1, 2, 3, 3]
    assert "exact evidence" in renderer.plans[-1]["repair"]["validation_error"]
    assert len(renderer.images) == 4  # one sheet plus three scenes, with no wasted image turns
    saved = await db.store.range_plan(job["id"], 3)
    assert saved["plan"]["scenes"][0]["evidence"] == QUOTE
    rows = await db.store.for_job(job["id"])
    assert len(rows) == 4
    retry = Renderer()
    await execute_range(db, job, retry)
    assert retry.plans == [] and retry.images == []
    assert {row["id"] for row in await db.store.for_job(job["id"])} == {row["id"] for row in rows}


@pytest.mark.asyncio
async def test_range_retry_resumes_chapter_checkpoints_without_rerendering(art_db):
    db = art_db
    result = await db.service.generate_range(
        db.novel, db.owner, from_chapter=1, to_chapter=3, force=True
    )
    job = await work.get_job(result["job_id"])
    failing = Renderer(fail_image=3)
    with pytest.raises(RuntimeError, match="transient"):
        await execute_range(db, job, failing)
    assert len(await db.store.for_job(job["id"])) == 2
    retry = Renderer()
    await execute_range(db, job, retry)
    assert len(retry.images) == 2
    assert [plan["chapter"] for plan in retry.plans] == [3]
    assert len(await db.store.for_job(job["id"])) == 4


@pytest.mark.asyncio
async def test_range_skips_existing_and_invalidation_removes_range_plan(art_db):
    db = art_db
    first = await enqueue(db, chapter=1)
    await execute(db, first, Renderer())
    await finish(first)
    result = await db.service.generate_range(
        db.novel, db.owner, from_chapter=1, to_chapter=3
    )
    job = await work.get_job(result["job_id"])
    renderer = Renderer()
    progress = await execute_range(db, job, renderer)
    assert progress["skipped"] == 1 and len(renderer.images) == 2
    async with db.pool.acquire() as conn:
        artifacts = PostgresCodexTransactionService(conn)
        assert await artifacts.has_chapter_artifacts(db.novel, (3,))
        await artifacts.invalidate_chapter_range(db.novel, 2, 2)
    assert await db.store.plan(job["id"]) is None
    assert await db.store.range_plan(job["id"], 2) is None
    assert await db.store.for_job(job["id"]) == []
    from novelwiki.modules.codex.adapters.outbound.illustration_range_store import (
        IllustrationRangeStore,
    )

    with pytest.raises(Conflict, match="invalidated"):
        await IllustrationRangeStore(db.pool, 2).save_plan(job["id"], {"plan": {}})
    with pytest.raises(Conflict, match="invalidated"):
        await execute_range(
            db, {**job, "progress": {"range_started": True}}, Renderer()
        )


@pytest.mark.asyncio
async def test_previous_illustration_context_hash_matches_full_chapter(art_db):
    db = art_db
    reading = PostgresReadingCodexGateway(db.pool)
    rows = await reading.previous_illustration_context(db.novel, 3, 2, 20)
    assert len(rows) == 2 and sum(len(row["text"]) for row in rows) <= 20
    for row in rows:
        assert row["source_hash"] == source_hash(
            await reading.illustration_snapshot(db.novel, row["chapter"])
        )


@pytest.mark.asyncio
async def test_legacy_luminous_art_remains_readable_but_new_direction_redesigns_sheets(art_db):
    db = art_db
    original = await enqueue(db)
    await execute(db, original, Renderer())
    await finish(original)
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE codex_art SET metadata=metadata-'style_revision' WHERE novel_id=$1",
            db.novel,
        )
    old_rows = await db.store.for_job(original["id"])
    scene = next(row for row in old_rows if row["kind"] == "scene")
    assert await db.service.image(db.novel, scene["id"], db.owner) == b"image-2"
    fresh = await enqueue(db)
    assert fresh["id"] != original["id"]
    assert fresh["options"]["style_revision"] == "soft-cel-anime-v2"
    renderer = Renderer()
    await execute(db, fresh, renderer)
    assert len(renderer.images) == 2  # Corrected sheet, then chapter scene.
    assert renderer.plans[0]["existing_characters"] == []
    assert all(metadata(row)["style_revision"] == "soft-cel-anime-v2"
               for row in await db.store.for_job(fresh["id"]))
    assert await db.store.get(db.novel, scene["id"])  # No global legacy-art deletion.


@pytest.mark.asyncio
async def test_painterly_direction_stores_separately_from_anime(art_db):
    db = art_db
    anime = await enqueue(db)
    await execute(db, anime, Renderer())
    await finish(anime)
    request = await db.service.generate(db.novel, 2, db.owner, style="painterly")
    job = await work.get_job(request["job_id"])
    renderer = Renderer()
    await execute(db, job, renderer)
    rows = await db.store.for_job(job["id"])
    assert len(rows) == 2
    assert all(row["style"] == "painterly" and metadata(row)["style_revision"] == "painterly-v1"
               for row in rows)
    assert renderer.plans[0]["existing_characters"] == []
    assert all("SEMI-REALISTIC PAINTERLY CINEMA" in prompt for prompt, _ in renderer.images)
