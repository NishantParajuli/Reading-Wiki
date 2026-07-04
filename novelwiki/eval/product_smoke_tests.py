"""End-to-end smoke test for Batch 9 through the real ASGI stack (TestClient).

Unlike product_reader_tests.py (which calls route functions directly), this drives the full
middleware → auth dependency → router → JSON serialization path for the new product surfaces,
so it catches router wiring, CSRF, cookie auth, and response-model issues. Runs against the
disposable per-session database the eval conftest forces us onto.

It is a *synchronous* test: TestClient runs the app in its own event loop/thread, so all direct
DB seeding here goes through short-lived asyncpg connections in a separate ``asyncio.run`` loop
(never the app's shared pool) to avoid cross-loop connection corruption.
"""
import asyncio

import asyncpg

from novelwiki.config.settings import settings

REQ = {"X-Tideglass-Request": "1"}


def _run(coro):
    return asyncio.run(coro)


async def _seed_novel(username: str) -> int:
    """Seed a public codex novel owned by ``username`` + reading progress + one active job,
    using a fresh connection to the (conftest-provisioned) disposable database."""
    conn = await asyncpg.connect(settings.DATABASE_URL)
    try:
        uid = await conn.fetchval("SELECT id FROM users WHERE username = $1;", username)
        nid = await conn.fetchval(
            "INSERT INTO novels (title, owner_id, visibility, codex_enabled, original_language) "
            "VALUES ('Smoke Novel', $1, 'public', TRUE, 'en') RETURNING id;", uid)
        await conn.execute(
            "INSERT INTO sources (novel_id, adapter, is_raw, language) VALUES ($1, 'fenrirealm', FALSE, 'en');", nid)
        for i in range(1, 4):
            await conn.execute(
                "INSERT INTO chapters (novel_id, number, title, content, translation_status) "
                "VALUES ($1, $2, $3, $4, 'done');", nid, i, f"Ch{i}", f"content {i}")
        await conn.execute(
            "INSERT INTO reading_progress (user_id, novel_id, last_chapter, max_chapter_read, scroll_pct) "
            "VALUES ($1, $2, 2, 2, 0);", uid, nid)
        await conn.execute(
            "INSERT INTO jobs (kind, novel_id, user_id, status, stage) "
            "VALUES ('scrape', $1, $2, 'running', 'scraping');", nid, uid)
        return nid
    finally:
        await conn.close()


async def _seed_cached_recap(novel_id: int, ceiling: float, answer: str) -> None:
    from novelwiki.agent.orchestrator import compute_query_hash
    from novelwiki.api.routes_product import RECAP_QUESTION
    conn = await asyncpg.connect(settings.DATABASE_URL)
    try:
        await conn.execute(
            "INSERT INTO query_cache (novel_id, query_hash, chapter_ceiling, answer_md, evidence_ids, created_at) "
            "VALUES ($1, $2, $3, $4, '{}'::jsonb, now());",
            novel_id, compute_query_hash(RECAP_QUESTION), ceiling, answer)
    finally:
        await conn.close()


def test_product_surfaces_end_to_end():
    from starlette.testclient import TestClient
    from novelwiki.api.app import app

    # https base_url so the Secure session/csrf cookies are actually sent back on later requests.
    with TestClient(app, base_url="https://testserver") as client:
        # Register (public auth mutation → needs the request header; sets session + csrf cookies).
        r = client.post("/api/auth/register",
                        json={"email": "smoke@t.test", "username": "smoker", "password": "sup3rsecret!"},
                        headers=REQ)
        assert r.status_code == 200, r.text

        home = client.get("/api/home")
        assert home.status_code == 200, home.text
        for key in ("continue_reading", "continue_listening", "active_jobs", "recent_imports", "newest"):
            assert key in home.json()

        act = client.get("/api/activity?status=active")
        assert act.status_code == 200 and "jobs" in act.json()

        disc = client.get("/api/discover?has_codex=true&sort=title")
        assert disc.status_code == 200

        # Seed a novel this user owns + reading progress, then re-check the reader surfaces.
        nid = _run(_seed_novel("smoker"))

        home2 = client.get("/api/home").json()
        assert any(n["id"] == nid for n in home2["continue_reading"])
        assert any(j["source"] == "job" and j["novel_id"] == nid for j in home2["active_jobs"])

        detail = client.get(f"/api/novels/{nid}").json()
        assert "provenance" in detail and detail["provenance"]["scraped"] is True

        est = client.get(f"/api/novels/{nid}/cost-estimate?action=codex_build").json()
        assert est["estimated_units"] == 1 and est["quota_kind"] == "codex_builds"

        health = client.get(f"/api/novels/{nid}/health").json()
        assert health["codex"]["missing"] is True and health["is_editor"] is True

        # Recap: seed a cached answer so the (verified-email-gated) provider path is skipped.
        _run(_seed_cached_recap(nid, 2, "Cached recap body."))
        csrf = client.cookies.get("tg_csrf")
        recap = client.post(f"/api/novels/{nid}/recap", json={"ceiling": 5},
                            headers={**REQ, "X-Tideglass-CSRF": csrf})
        assert recap.status_code == 200, recap.text
        rb = recap.json()
        assert rb["answer"] == "Cached recap body."
        assert rb["effective_ceiling"] == 2 and rb["ceiling_clamped"] is True
