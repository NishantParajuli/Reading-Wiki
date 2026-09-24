from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from novelwiki.modules.codex.adapters.outbound.ingest import chunk, embed


@pytest.fixture
def bounded_word_counter(monkeypatch):
    """A deterministic tokenizer that fails promptly if chunking stops advancing."""
    calls = 0

    def count_tokens(text):
        nonlocal calls
        calls += 1
        assert calls < 100, "chunking repeated the retained overlap without advancing"
        return len(text.split())

    monkeypatch.setattr(chunk, "count_tokens", count_tokens)


@pytest.mark.parametrize("next_piece", ["one two three four five", "one two three four five six"])
def test_overlap_yields_to_long_next_piece(bounded_word_counter, next_piece):
    assert chunk.chunk_chapter_text(
        f"Opening.\n\n{next_piece}", target_tokens=5, overlap_tokens=2,
    ) == ["Opening.", next_piece]


def test_overlap_larger_than_target_still_makes_progress(bounded_word_counter):
    assert chunk.chunk_chapter_text(
        "First piece.\n\nSecond piece.\n\nThird piece.",
        target_tokens=4,
        overlap_tokens=100,
    ) == ["First piece.\n\nSecond piece.", "Second piece.\n\nThird piece."]


def test_final_oversized_piece_is_not_duplicated_as_overlap(bounded_word_counter):
    assert chunk.chunk_chapter_text(
        "one two three four five six", target_tokens=5, overlap_tokens=10,
    ) == ["one two three four five six"]


@pytest.mark.parametrize("target,overlap", [(0, 1), (-1, 1), (5, -1)])
def test_chunking_rejects_invalid_token_budgets(target, overlap):
    with pytest.raises(ValueError):
        chunk.chunk_chapter_text("Chapter text.", target_tokens=target, overlap_tokens=overlap)


def test_literal_special_token_markers_are_preserved_as_chapter_text():
    text = "She typed <|endoftext|> and pressed Enter."

    assert chunk.count_tokens(text) > 0
    assert chunk.chunk_chapter_text(text) == [text]


class _EmbeddingConnection:
    def __init__(self):
        self.rows = {
            1: {"id": 1, "novel_id": 7, "text": "Original passage", "embedding": None},
            2: {"id": 2, "novel_id": 7, "text": "Unchanged passage", "embedding": None},
        }

    async def fetch(self, *_args):
        return [dict(row) for row in self.rows.values()]

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, statement, vector, chunk_id, *conditions):
        row = self.rows[chunk_id]
        if conditions:
            novel_id, source_text = conditions
            assert "AND text = $4" in statement
            assert "AND embedding IS NULL" in statement
            if row["novel_id"] != novel_id or row["text"] != source_text or row["embedding"] is not None:
                return "UPDATE 0"
        row["embedding"] = vector
        return "UPDATE 1"


class _EmbeddingPool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent_change", ["text", "embedding"])
async def test_embedding_write_preserves_concurrent_changes(monkeypatch, concurrent_change):
    connection = _EmbeddingConnection()

    async def pool():
        return _EmbeddingPool(connection)

    async def embeddings(texts):
        assert texts == ["Original passage", "Unchanged passage"]
        connection.rows[1][concurrent_change] = (
            "Edited passage" if concurrent_change == "text" else "[0.0,1.0]"
        )
        return [[1.0, 0.0], [0.5, 0.5]]

    monkeypatch.setattr(embed, "get_db_pool", pool)
    runtime = SimpleNamespace(ai=SimpleNamespace(get_embeddings_batch=embeddings))

    count = await embed.embed_missing_chunks(7, runtime=runtime)

    assert count == 1
    assert connection.rows[2]["embedding"] == "[0.5,0.5]"
    if concurrent_change == "text":
        assert connection.rows[1]["text"] == "Edited passage"
        assert connection.rows[1]["embedding"] is None
    else:
        assert connection.rows[1]["embedding"] == "[0.0,1.0]"
