#!/usr/bin/env python3
"""Seed non-private fixtures for the opt-in real-backend Playwright suite."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novelwiki.modules.codex.adapters.outbound.agent import compute_query_hash
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


def make_epub(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
 <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""")
        archive.writestr("OEBPS/content.opf", """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
 <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">real-browser</dc:identifier><dc:title>Browser Import Fixture</dc:title><dc:language>en</dc:language></metadata>
 <manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest>
 <spine><itemref idref="chapter"/></spine>
</package>""")
        archive.writestr("OEBPS/nav.xhtml", """<html xmlns="http://www.w3.org/1999/xhtml"><body><nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops"><ol><li><a href="chapter.xhtml">Chapter 1</a></li></ol></nav></body></html>""")
        archive.writestr("OEBPS/chapter.xhtml", """<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter 1</title></head><body><h1>Chapter 1</h1><p>The browser import fixture crossed the real upload boundary.</p></body></html>""")


async def seed(username: str, suffix: str) -> dict:
    connection = await asyncpg.connect(_host_url(os.environ.get("DATABASE_URL", settings.DATABASE_URL)))
    try:
        user = await connection.fetchrow(
            "UPDATE users SET email_verified=TRUE, role='admin', status='active' "
            "WHERE username=$1 RETURNING id", username,
        )
        if not user:
            raise RuntimeError(f"registered fixture user {username!r} was not found")
        user_id = int(user["id"])
        novel_id = int(await connection.fetchval(
            "INSERT INTO novels (title, author, description, original_language, codex_enabled, "
            "owner_id, visibility) VALUES ($1, 'Fixture Author', 'Non-private browser fixture', "
            "'en', TRUE, $2, 'public') RETURNING id",
            f"Browser fixture {suffix}", user_id,
        ))
        source_id = int(await connection.fetchval(
            "INSERT INTO sources (novel_id, adapter, start_url, language, is_raw) "
            "VALUES ($1, 'epub', 'fixture.epub', 'en', FALSE) RETURNING id", novel_id,
        ))
        await connection.execute(
            "INSERT INTO chapters (novel_id, number, source_id, title, content, language, "
            "is_translated, translation_status, word_count, content_version, kind) "
            "VALUES ($1, 1, $2, 'The Fixture', $3, 'en', TRUE, 'done', 9, 1, 'chapter')",
            novel_id, source_id, "The fixture guide meets the reader at the real backend boundary.",
        )
        await connection.execute(
            "INSERT INTO library_entries (user_id, novel_id, shelf) VALUES ($1, $2, 'reading') "
            "ON CONFLICT (user_id, novel_id) DO NOTHING", user_id, novel_id,
        )
        question = "Who is the fixture guide?"
        await connection.execute(
            "INSERT INTO query_cache (novel_id, query_hash, chapter_ceiling, answer_md, evidence_ids) "
            "VALUES ($1, $2, 1, $3, '{}'::jsonb)",
            novel_id, compute_query_hash(question),
            "The fixture guide is the seeded character at the browser/backend boundary.",
        )
        audio = b"OggS-real-browser-fixture-audio"
        for version in (1, 2):
            rel = f"{novel_id}/narrator/ch1__v{version}.opus"
            destination = Path(settings.AUDIO_DIR) / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(audio)
            await connection.execute(
                "INSERT INTO chapter_audio (novel_id, chapter, voice_id, language, content_version, "
                "audio_path, duration_seconds, file_bytes) VALUES ($1, 1, 'narrator', 'en', $2, $3, 1, $4)",
                novel_id, version, rel, len(audio),
            )
        job_id = int(await connection.fetchval(
            "INSERT INTO jobs (kind, novel_id, user_id, status, stage, options, not_before) "
            "VALUES ('scrape', $1, $2, 'waiting_provider', 'fixture wait', '{}'::jsonb, "
            "now() + interval '1 hour') RETURNING id", novel_id, user_id,
        ))
        return {"user_id": user_id, "novel_id": novel_id, "job_id": job_id,
                "question": question, "voice_id": "narrator", "audio_bytes": len(audio)}
    finally:
        await connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username")
    parser.add_argument("--suffix", default="fixture")
    parser.add_argument("--make-epub", type=Path)
    args = parser.parse_args()
    if args.make_epub:
        make_epub(args.make_epub)
        print(args.make_epub.resolve())
        return 0
    if not args.username:
        parser.error("--username is required unless --make-epub is used")
    print(json.dumps(asyncio.run(seed(args.username, args.suffix))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
