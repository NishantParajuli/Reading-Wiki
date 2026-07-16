from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_clearing_chapter_invalidates_downstream_checkpoints():
    from novelwiki.modules.codex.adapters.outbound.ingest.extract import (
        _clear_extraction_chapter,
    )

    calls = []

    class Connection:
        async def execute(self, statement, *args):
            calls.append((" ".join(statement.split()), args))

    await _clear_extraction_chapter(Connection(), novel_id=7, chapter=3.0)

    checkpoint_call = calls[-1]
    assert checkpoint_call == (
        "DELETE FROM extraction_state WHERE novel_id=$1 AND chapter >= $2;",
        (7, 3.0),
    )


@pytest.mark.asyncio
async def test_rebuilding_invalidated_checkpoint_clears_orphaned_artifacts(monkeypatch):
    from novelwiki.modules.codex.adapters.outbound.ingest import extract

    cleared = []

    async def clear_chapter(connection, novel_id, chapter):
        cleared.append((connection, novel_id, chapter))

    async def no_op(*_args, **_kwargs):
        return None

    async def one_chunk(*_args, **_kwargs):
        return "[chunk 1]\nChapter text.", {1}, [1]

    monkeypatch.setattr(extract, "_clear_extraction_chapter", clear_chapter)
    monkeypatch.setattr(extract, "clear_caches", no_op)
    monkeypatch.setattr(extract, "_load_chapter_chunks", one_chunk)

    class Connection:
        async def fetchrow(self, *_args, **_kwargs):
            return None

        async def execute(self, *_args, **_kwargs):
            return None

    connection = Connection()
    service = extract.PostgresCodexExtractionTransactionService(
        connection,
        runtime=object(),
        entity_resolver=None,
    )
    empty_extraction = {key: [] for key in extract.EXTRACTION_KEYS}

    result = await service.commit_extraction(
        7,
        3.0,
        empty_extraction,
        "Rebuilt summary.",
        chapter_snapshot={"content": "Chapter text."},
        expected_source_hash="source-hash",
        resolved_refs={},
        roster_refs={},
    )

    assert cleared == [(connection, 7, 3.0)]
    assert result == {"status": "done", "idempotent": False}
