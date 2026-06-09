import re
import logging
import asyncio
import tiktoken
from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool, close_db_pool

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

async def chunk_chapter(novel_id: int, chapter_number: float, force: bool = False) -> int:
    """
    Fetches readable chapter text, chunks it, and writes chunks to the chunks table.
    Deletes prior chunks first if force=True.
    """
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        chapter = await conn.fetchrow(
            "SELECT content FROM chapters WHERE number = $1 AND novel_id = $2;",
            chapter_number, novel_id
        )
        if not chapter or not chapter["content"]:
            logger.error(f"Chapter {chapter_number} not found (or has no content) in DB.")
            return 0

        # Check if chunks already exist
        existing = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM chunks WHERE chapter = $1 AND novel_id = $2);",
            chapter_number, novel_id
        )
        if existing and not force:
            logger.info(f"Chapter {chapter_number} chunks already exist. Skipping.")
            return 0

        chunks = chunk_chapter_text(chapter["content"])

        # Deletion pass (idempotent overwrite)
        if existing:
            await conn.execute("DELETE FROM chunks WHERE chapter = $1 AND novel_id = $2;", chapter_number, novel_id)

        # Insert chunks
        async with conn.transaction():
            for idx, chunk_text in enumerate(chunks):
                token_count = count_tokens(chunk_text)
                await conn.execute(
                    """
                    INSERT INTO chunks (novel_id, chapter, chunk_index, text, token_count)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (novel_id, chapter, chunk_index) DO UPDATE
                    SET text = EXCLUDED.text, token_count = EXCLUDED.token_count, embedding = NULL;
                    """,
                    novel_id, chapter_number, idx, chunk_text, token_count
                )

        logger.info(f"Successfully chunked Chapter {chapter_number} into {len(chunks)} chunks.")
        return len(chunks)

async def chunk_all_chapters(
    novel_id: int,
    force: bool = False,
    from_chapter: float | None = None,
    to_chapter: float | None = None,
) -> int:
    """Chunks chapters currently in the database, optionally limited to a range."""
    pool = await get_db_pool()
    conditions = ["novel_id = $1"]
    args: list = [novel_id]
    if from_chapter is not None:
        args.append(from_chapter)
        conditions.append(f"number >= ${len(args)}")
    if to_chapter is not None:
        args.append(to_chapter)
        conditions.append(f"number <= ${len(args)}")
    where = " WHERE " + " AND ".join(conditions)

    async with pool.acquire() as conn:
        rows = await conn.fetch(f"SELECT number FROM chapters{where} ORDER BY number ASC;", *args)

    total_chunks = 0
    for row in rows:
        num = float(row["number"])
        cnt = await chunk_chapter(novel_id, num, force=force)
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
