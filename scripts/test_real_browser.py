#!/usr/bin/env python3
"""Run real Playwright paths against disposable PostgreSQL and a local FastAPI process."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from novelwiki.platform.config import settings


def _host_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname != "host.docker.internal":
        return url
    host = "127.0.0.1"
    if parsed.port:
        host += f":{parsed.port}"
    if parsed.username:
        credentials = parsed.username
        if parsed.password:
            credentials += f":{parsed.password}"
        host = f"{credentials}@{host}"
    return urlunparse(parsed._replace(netloc=host))


def _with_database(url: str, name: str) -> str:
    return urlunparse(urlparse(url)._replace(path=f"/{name}"))


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def _create(superuser_url: str, database_url: str, name: str) -> None:
    admin = await asyncpg.connect(superuser_url)
    try:
        await admin.execute(f"CREATE DATABASE {_quote(name)}")
    finally:
        await admin.close()
    from novelwiki.db.schema import DDL_QUERIES
    connection = await asyncpg.connect(database_url)
    try:
        for query in DDL_QUERIES:
            await connection.execute(query)
        if settings.EMBED_DIM <= 2000:
            await connection.execute(
                "CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks "
                "USING hnsw (embedding vector_cosine_ops)"
            )
            await connection.execute(
                "CREATE INDEX IF NOT EXISTS entities_name_emb ON entities "
                "USING hnsw (name_embedding vector_cosine_ops)"
            )
    finally:
        await connection.close()


async def _drop(superuser_url: str, name: str) -> None:
    admin = await asyncpg.connect(superuser_url)
    try:
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname=$1 AND pid<>pg_backend_pid()", name,
        )
        await admin.execute(f"DROP DATABASE IF EXISTS {_quote(name)}")
    finally:
        await admin.close()


def _wait_for_server(process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"FastAPI exited before readiness (code {process.returncode})")
        try:
            with urllib.request.urlopen("http://127.0.0.1:8011/health", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("FastAPI did not become ready within 45 seconds")


def main() -> int:
    superuser_url = _host_url(os.environ.get("TEST_DB_SUPERUSER_URL", settings.DB_SUPERUSER_URL))
    base_url = _host_url(os.environ.get("TEST_DATABASE_URL", settings.DATABASE_URL))
    base = re.sub(r"[^a-z0-9_]+", "_", urlparse(base_url).path.lstrip("/").lower())[:18]
    name = f"tg_playwright_{base}_{os.getpid()}_{uuid.uuid4().hex[:8]}"[:63]
    database_url = _with_database(base_url, name)
    data_root = Path(tempfile.mkdtemp(prefix="tg-playwright-"))
    server = None
    try:
        asyncio.run(_create(superuser_url, database_url, name))
        environment = {
            **os.environ,
            "DATABASE_URL": database_url,
            "DB_SUPERUSER_URL": superuser_url,
            "COOKIE_SECURE": "false",
            "ALLOWED_ORIGINS": "http://127.0.0.1:4173",
            "PUBLIC_BASE_URL": "http://127.0.0.1:8011",
            "IMPORT_DIR": str(data_root / "imports"),
            "IMPORT_INCOMING_DIR": str(data_root / "imports" / "incoming"),
            "ASSET_DIR": str(data_root / "assets"),
            "AUDIO_DIR": str(data_root / "audio"),
            "BM25_INDEX_PATH": str(data_root / "bm25"),
            "REAL_BACKEND": "1",
            "VITE_API_PROXY": "http://127.0.0.1:8011",
        }
        server = subprocess.Popen(
            ["uv", "run", "uvicorn", "novelwiki.api.app:app", "--host", "127.0.0.1",
             "--port", "8011", "--log-level", "warning"],
            cwd=ROOT, env=environment,
        )
        _wait_for_server(server)
        return subprocess.run(
            ["npm", "run", "test:e2e", "--", "e2e/real-backend.spec.js", "--workers=1"],
            cwd=ROOT / "novelwiki" / "frontend", env=environment,
        ).returncode
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        asyncio.run(_drop(superuser_url, name))
        shutil.rmtree(data_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
