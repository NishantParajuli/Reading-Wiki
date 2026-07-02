import io
import json

import pytest
import pytest_asyncio
from fastapi import BackgroundTasks, HTTPException
from httpx import ASGITransport, AsyncClient

import novelwiki.db.connection as db_connection
from novelwiki.api import routes
from novelwiki.config.settings import settings
from novelwiki.db.connection import close_db_pool, get_db_pool
from novelwiki.db.schema import init_database
from novelwiki.importer import storage


def _png(w: int = 2, h: int = 2) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (80, 120, 160)).save(buf, "PNG")
    return buf.getvalue()


async def _reset_pool():
    try:
        await close_db_pool()
    except RuntimeError:
        pass
    db_connection._pool = None


@pytest_asyncio.fixture()
async def asset_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ASSET_DIR", str(tmp_path / "assets"))
    storage.ensure_dirs()
    await _reset_pool()
    await init_database()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM assets;")
            await conn.execute("DELETE FROM import_jobs;")
            await conn.execute("DELETE FROM novels CASCADE;")
            await conn.execute("DELETE FROM users CASCADE;")
            owner = await conn.fetchrow(
                """
                INSERT INTO users (email, username, display_name, role, email_verified)
                VALUES ('asset-owner@example.test', 'assetowner', 'Asset Owner', 'user', TRUE)
                RETURNING *;
                """
            )
            other = await conn.fetchrow(
                """
                INSERT INTO users (email, username, display_name, role, email_verified)
                VALUES ('asset-other@example.test', 'assetother', 'Asset Other', 'user', TRUE)
                RETURNING *;
                """
            )
            admin = await conn.fetchrow(
                """
                INSERT INTO users (email, username, display_name, role, email_verified)
                VALUES ('asset-admin@example.test', 'assetadmin', 'Asset Admin', 'admin', TRUE)
                RETURNING *;
                """
            )
            private_novel = await conn.fetchval(
                "INSERT INTO novels (title, owner_id, visibility) VALUES ('Private Assets', $1, 'private') RETURNING id;",
                owner["id"],
            )
            public_novel = await conn.fetchval(
                "INSERT INTO novels (title, owner_id, visibility) VALUES ('Public Assets', $1, 'public') RETURNING id;",
                owner["id"],
            )
            job_id = await conn.fetchval(
                """
                INSERT INTO import_jobs (format, original_path, status, user_id, detected_meta)
                VALUES ('epub', '/tmp/book.epub', 'awaiting_review', $1, '{}'::jsonb)
                RETURNING id;
                """,
                owner["id"],
            )
    yield {
        "owner": dict(owner),
        "other": dict(other),
        "admin": dict(admin),
        "private_novel": int(private_novel),
        "public_novel": int(public_novel),
        "job_id": int(job_id),
    }
    await _reset_pool()


def test_asset_urls_use_authenticated_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ASSET_DIR", str(tmp_path / "assets"))
    storage.ensure_dirs()
    sha, ext = storage.stage_asset(12, _png(), "image/png")

    assert storage.staged_asset_url(12, sha, ext).startswith("/api/assets/import-jobs/12/")
    assert storage.asset_url(34, sha, ext).startswith("/api/assets/novels/34/")


def test_svg_asset_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ASSET_DIR", str(tmp_path / "assets"))
    storage.ensure_dirs()
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

    with pytest.raises(ValueError, match="SVG"):
        storage.stage_asset(1, svg, "image/svg+xml")


@pytest.mark.asyncio
async def test_logged_out_asset_request_returns_401():
    from novelwiki.api.app import app
    filename = f"{'a' * 64}.png"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(f"/api/assets/novels/1/{filename}")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_private_committed_asset_requires_novel_read_access(asset_db):
    data = _png()
    sha = storage.sha256_bytes(data)
    filename = f"{sha}.png"
    path = storage.asset_file_path(asset_db["private_novel"], filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO assets (novel_id, sha256, path, mime, kind)
            VALUES ($1, $2, $3, 'image/png', 'cover');
            """,
            asset_db["private_novel"], sha, storage.asset_rel(asset_db["private_novel"], sha, "png"),
        )

    with pytest.raises(HTTPException) as exc:
        await routes.api_novel_asset(asset_db["private_novel"], filename, user=asset_db["other"])
    assert exc.value.status_code == 404

    response = await routes.api_novel_asset(asset_db["private_novel"], filename, user=asset_db["owner"])
    assert response.media_type == "image/png"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.asyncio
async def test_reader_rich_html_rewrites_old_asset_urls_to_authenticated_routes(asset_db):
    sha = "b" * 64
    old_url = f"/assets/{asset_db['private_novel']}/{sha}.png"
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        source_id = await conn.fetchval(
            """
            INSERT INTO sources (novel_id, adapter, start_url, config, language, is_raw)
            VALUES ($1, 'epub', '/tmp/book.epub', '{}'::jsonb, 'en', FALSE)
            RETURNING id;
            """,
            asset_db["private_novel"],
        )
        await conn.execute(
            """
            INSERT INTO chapters (novel_id, number, source_id, title, content, raw_html, language, translation_status)
            VALUES ($1, 1, $2, 'One', 'Reader text', $3, 'en', 'done');
            """,
            asset_db["private_novel"], source_id, f'<figure><img src="{old_url}" alt=""></figure>',
        )

    payload = await routes.api_get_chapter(
        asset_db["private_novel"],
        1.0,
        BackgroundTasks(),
        user=asset_db["owner"],
    )

    assert f'/api/assets/novels/{asset_db["private_novel"]}/{sha}.png' in payload["rich_html"]
    assert old_url not in payload["rich_html"]


@pytest.mark.asyncio
async def test_public_committed_asset_available_to_logged_in_reader(asset_db):
    data = _png()
    sha = storage.sha256_bytes(data)
    filename = f"{sha}.png"
    path = storage.asset_file_path(asset_db["public_novel"], filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO assets (novel_id, sha256, path, mime, kind)
            VALUES ($1, $2, $3, 'image/png', 'cover');
            """,
            asset_db["public_novel"], sha, storage.asset_rel(asset_db["public_novel"], sha, "png"),
        )

    response = await routes.api_novel_asset(asset_db["public_novel"], filename, user=asset_db["other"])
    assert response.media_type == "image/png"


@pytest.mark.asyncio
async def test_staged_import_asset_requires_job_ownership(asset_db):
    data = _png()
    sha, ext = storage.stage_asset(asset_db["job_id"], data, "image/png")
    filename = f"{sha}.{ext}"
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE import_jobs SET detected_meta = $2::jsonb WHERE id = $1;",
            asset_db["job_id"], json.dumps({"cover_sha": sha}),
        )

    with pytest.raises(HTTPException) as exc:
        await routes.api_import_job_asset(asset_db["job_id"], filename, user=asset_db["other"])
    assert exc.value.status_code == 404

    response = await routes.api_import_job_asset(asset_db["job_id"], filename, user=asset_db["owner"])
    assert response.media_type == "image/png"


@pytest.mark.asyncio
async def test_asset_path_traversal_is_rejected(asset_db):
    with pytest.raises(HTTPException) as exc:
        await routes.api_novel_asset(asset_db["private_novel"], "../secret.png", user=asset_db["owner"])
    assert exc.value.status_code == 404
