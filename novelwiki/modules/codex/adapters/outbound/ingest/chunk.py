import re
import logging
import asyncio
from collections.abc import Awaitable, Callable

import tiktoken
from novelwiki.platform.config import settings
from novelwiki.platform.database import get_db_pool, close_db_pool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_encoder = None

def get_encoder():
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder

def count_tokens(text: str) -> int:
    return len(get_encoder().encode(text))

def split_by_sentences(text: str) -> list[str]:
    """Splits text by typical sentence boundaries, preserving punctuation."""
    # Split on period, exclamation, or question mark followed by space or end of string
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]

def chunk_chapter_text(
    text: str, 
    target_tokens: int = None, 
    overlap_tokens: int = None
) -> list[str]:
    """
    Chunks text strictly within sentence/paragraph boundaries.
    Tolerates paragraphs/sentences that are larger than target_tokens by placing them in their own chunk.
    """
    if target_tokens is None:
        target_tokens = settings.CHUNK_TARGET_TOKENS
    if overlap_tokens is None:
        overlap_tokens = settings.CHUNK_OVERLAP

    # 1. Split into paragraphs
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    
    # 2. Refine into pieces (split paragraphs into sentences ONLY if paragraph > target_tokens)
    pieces = []
    for p in paragraphs:
        p_tok = count_tokens(p)
        if p_tok > target_tokens:
            sentences = split_by_sentences(p)
            for s in sentences:
                pieces.append(s)
        else:
            pieces.append(p)
            
    # 3. Slide over pieces to group them into chunks with paragraph/sentence overlap
    chunks = []
    current_pieces = []
    current_tokens = 0
    
    i = 0
    while i < len(pieces):
        piece = pieces[i]
        piece_tokens = count_tokens(piece)
        
        if current_tokens + piece_tokens <= target_tokens:
            current_pieces.append(piece)
            current_tokens += piece_tokens
            i += 1
        else:
            if not current_pieces:
                # Force-include the oversized piece
                current_pieces.append(piece)
                current_tokens += piece_tokens
                i += 1
            
            # Save the chunk
            chunks.append("\n\n".join(current_pieces))
            
            # Backtrack pieces to form the overlap for the next chunk
            overlap_accum = 0
            backtrack_count = 0
            for item in reversed(current_pieces):
                item_tok = count_tokens(item)
                if overlap_accum + item_tok <= overlap_tokens:
                    overlap_accum += item_tok
                    backtrack_count += 1
                else:
                    break
            
            if backtrack_count > 0:
                current_pieces = current_pieces[-backtrack_count:]
                current_tokens = overlap_accum
            else:
                current_pieces = []
                current_tokens = 0
                
    if current_pieces:
        chunks.append("\n\n".join(current_pieces))
        
    return chunks

async def chunk_chapter(
    novel_id: int, chapter_number: float, force: bool = False, *, runtime
) -> int:
    """
    Fetches readable chapter text, chunks it, and writes chunks to the chunks table.

    A deterministic force rebuild updates rows by ``chunk_index`` instead of
    delete/reinsert, preserving chunk IDs and every citation that points at them.
    If the generated text actually changed while an extraction checkpoint still
    exists, the operation fails closed until that extraction is invalidated.
    """
    chapter = await runtime.reading.chapter_snapshot(
        novel_id, chapter_number
    )
    if not chapter or not chapter["content"]:
        logger.error(f"Chapter {chapter_number} not found (or has no content) in DB.")
        return 0
    pool = await get_db_pool()
    if (chapter.get("kind") or "chapter") not in {"chapter", "interlude"}:
        async with pool.acquire() as conn:
            async with conn.transaction():
                dependent = await conn.fetchval(
                    """
                    SELECT
                      EXISTS (SELECT 1 FROM extraction_state WHERE novel_id=$1 AND chapter=$2)
                      OR EXISTS (SELECT 1 FROM entities WHERE novel_id=$1 AND first_seen_chapter=$2)
                      OR EXISTS (SELECT 1 FROM entity_descriptions WHERE novel_id=$1 AND chapter=$2)
                      OR EXISTS (SELECT 1 FROM entity_aliases WHERE novel_id=$1 AND revealed_at_chapter=$2)
                      OR EXISTS (SELECT 1 FROM identity_links WHERE novel_id=$1 AND revealed_at_chapter=$2)
                      OR EXISTS (SELECT 1 FROM entity_facts WHERE novel_id=$1 AND chapter=$2)
                      OR EXISTS (SELECT 1 FROM relationships WHERE novel_id=$1 AND chapter=$2)
                      OR EXISTS (SELECT 1 FROM events WHERE novel_id=$1 AND chapter=$2)
                      OR EXISTS (SELECT 1 FROM chapter_summaries WHERE novel_id=$1 AND chapter=$2)
                      OR EXISTS (SELECT 1 FROM entity_activity WHERE novel_id=$1 AND chapter=$2)
                      OR EXISTS (SELECT 1 FROM entity_state_transitions WHERE novel_id=$1 AND chapter=$2)
                      OR EXISTS (SELECT 1 FROM relationship_state_transitions WHERE novel_id=$1 AND chapter=$2)
                      OR EXISTS (SELECT 1 FROM plot_thread_updates WHERE novel_id=$1 AND chapter=$2)
                      OR EXISTS (SELECT 1 FROM extraction_contexts WHERE novel_id=$1 AND chapter=$2)
                      OR EXISTS (SELECT 1 FROM memory_segments WHERE novel_id=$1
                                    AND $2 BETWEEN start_chapter AND through_chapter);
                    """,
                    novel_id, chapter_number,
                )
                if dependent:
                    raise RuntimeError(
                        "non-narrative chapter has structured Codex dependencies; "
                        "run reset-codex before the v2 rebuild"
                    )
                result = await conn.execute(
                    "DELETE FROM chunks WHERE novel_id=$1 AND chapter=$2;",
                    novel_id, chapter_number,
                )
        removed = int(result.rsplit(" ", 1)[-1])
        if removed:
            logger.info(
                "Removed %s stale non-narrative chunks for chapter %s.",
                removed, chapter_number,
            )
        return 0
    async with pool.acquire() as conn:
        chunks = chunk_chapter_text(chapter["content"])
        async with conn.transaction():
            existing_rows = await conn.fetch(
                "SELECT id,chunk_index,text FROM chunks "
                "WHERE chapter=$1 AND novel_id=$2 ORDER BY chunk_index FOR UPDATE;",
                chapter_number, novel_id,
            )
            if existing_rows and not force:
                logger.info(f"Chapter {chapter_number} chunks already exist. Skipping.")
                return 0

            existing_by_index = {
                int(row["chunk_index"]): row["text"] for row in existing_rows
            }
            changed = (
                set(existing_by_index) != set(range(len(chunks)))
                or any(existing_by_index.get(index) != text for index, text in enumerate(chunks))
            )
            if existing_rows and changed:
                checkpointed = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM extraction_state "
                    "WHERE novel_id=$1 AND chapter=$2);",
                    novel_id, chapter_number,
                )
                if checkpointed:
                    raise RuntimeError(
                        "refusing to change checkpointed chunk text; invalidate the chapter "
                        "extraction before re-chunking"
                    )

            for idx, chunk_text in enumerate(chunks):
                token_count = count_tokens(chunk_text)
                await conn.execute(
                    """
                    INSERT INTO chunks (novel_id, chapter, chunk_index, text, token_count)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (novel_id, chapter, chunk_index) DO UPDATE
                    SET text = EXCLUDED.text,
                        token_count = EXCLUDED.token_count,
                        embedding = CASE
                          WHEN chunks.text IS NOT DISTINCT FROM EXCLUDED.text
                          THEN chunks.embedding ELSE NULL END;
                    """,
                    novel_id, chapter_number, idx, chunk_text, token_count
                )
            await conn.execute(
                "DELETE FROM chunks WHERE novel_id=$1 AND chapter=$2 AND chunk_index >= $3;",
                novel_id, chapter_number, len(chunks),
            )

        logger.info(f"Successfully chunked Chapter {chapter_number} into {len(chunks)} chunks.")
        return len(chunks)

async def chunk_all_chapters(
    novel_id: int,
    force: bool = False,
    from_chapter: float | None = None,
    to_chapter: float | None = None,
    cancel_check: Callable[[], Awaitable[None]] | None = None,
    *,
    runtime,
) -> int:
    """Chunks chapters currently in the database, optionally limited to a range.

    ``cancel_check`` is called between chapters so durable jobs can stop without
    finishing a whole-book pass. The callback signals cancellation by raising the
    worker's cancellation exception.
    """
    numbers = await runtime.reading.chapter_numbers(
        novel_id, from_chapter, to_chapter, True, False
    )

    total_chunks = 0
    for num in numbers:
        if cancel_check is not None:
            await cancel_check()
        cnt = await chunk_chapter(novel_id, num, force=force, runtime=runtime)
        total_chunks += cnt

    return total_chunks

if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv

    async def main():
        novel_id = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1
        cnt = await chunk_all_chapters(novel_id, force=force)
        logger.info(f"Chunked a total of {cnt} chunks.")
        await close_db_pool()

    asyncio.run(main())
