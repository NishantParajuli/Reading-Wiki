import logging
import asyncio
from collections.abc import Awaitable, Callable

from novelwiki.platform.database import get_db_pool, close_db_pool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def embed_missing_chunks(
    novel_id: int,
    from_chapter: float | None = None,
    to_chapter: float | None = None,
    cancel_check: Callable[[], Awaitable[None]] | None = None,
    *,
    runtime,
) -> int:
    """
    Identifies all chunks where embedding IS NULL (optionally within a chapter range)
    and batch-embeds them. Normalizes outputs (cosine) and writes them as pgvector.
    """
    pool = await get_db_pool()

    conditions = ["embedding IS NULL", "novel_id = $1"]
    args: list = [novel_id]
    if from_chapter is not None:
        args.append(from_chapter)
        conditions.append(f"chapter >= ${len(args)}")
    if to_chapter is not None:
        args.append(to_chapter)
        conditions.append(f"chapter <= ${len(args)}")
    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT id, text FROM chunks WHERE {where} ORDER BY id ASC;", *args
        )

    if not rows:
        logger.info("No chunks are missing embeddings.")
        return 0

    logger.info(f"Found {len(rows)} chunks missing embeddings. Starting embedding generation...")

    batch_size = 16
    embedded_count = 0

    for idx in range(0, len(rows), batch_size):
        if cancel_check is not None:
            await cancel_check()
        batch = rows[idx : idx + batch_size]
        batch_ids = [r["id"] for r in batch]
        batch_texts = [r["text"] for r in batch]

        logger.info(f"Embedding batch of {len(batch)} chunks (IDs: {batch_ids[0]}-{batch_ids[-1]})...")
        try:
            vectors = await runtime.ai.get_embeddings_batch(batch_texts)
        except Exception as e:
            logger.error(f"Failed to embed batch starting with ID {batch_ids[0]}: {e}")
            # Skip and proceed to keep progress rolling for other batches
            continue

        # A cancel may arrive while the provider request is in flight. Check again
        # before persisting the response or starting another paid request.
        if cancel_check is not None:
            await cancel_check()

        if len(vectors) != len(batch):
            logger.error(f"Embedding size mismatch! Expected {len(batch)} vectors, got {len(vectors)}")
            continue

        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for chunk_id, vector in zip(batch_ids, vectors):
                        vector_str = "[" + ",".join(map(str, vector)) + "]"
                        await conn.execute(
                            "UPDATE chunks SET embedding = $1::vector WHERE id = $2;",
                            vector_str, chunk_id
                        )

            embedded_count += len(batch)
            logger.info(f"Successfully embedded {embedded_count}/{len(rows)} chunks.")
        except Exception as e:
            logger.error(f"Failed to embed batch starting with ID {batch_ids[0]}: {e}")

    return embedded_count

if __name__ == "__main__":
    import sys
    async def main():
        novel_id = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1
        cnt = await embed_missing_chunks(novel_id)
        logger.info(f"Completed batch embedding run. {cnt} chunks processed.")
        await close_db_pool()

    asyncio.run(main())
