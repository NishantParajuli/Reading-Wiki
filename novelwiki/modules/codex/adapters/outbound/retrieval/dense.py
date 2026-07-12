import logging
from novelwiki.platform.database import get_db_pool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def dense_search(
    novel_id: int, query: str, chapter_ceiling: float, k: int = 50, *, runtime
) -> list[dict]:
    """
    Computes query embedding and performs a pgvector cosine similarity search
    scoped to a single novel, pre-filtering strictly where chapter <= chapter_ceiling.
    Returns: [{"id": int, "chapter": float, "text": str, "score": float}]
    """
    try:
        # 1. Embed query
        q_vector = await runtime.ai.get_embedding(query)
        if not q_vector:
            logger.warning("Failed to generate embedding for query.")
            return []
            
        # Format vector as string for pgvector casting '[v1, v2, ...]'
        q_vector_str = "[" + ",".join(map(str, q_vector)) + "]"
        
        # 2. Search DB
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # 1 - (embedding <=> q_vector) represents cosine similarity
            rows = await conn.fetch(
                """
                SELECT id, chapter, text, 1 - (embedding <=> $1::vector) AS score
                FROM chunks
                WHERE chapter <= $2 AND novel_id = $4 AND embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector
                LIMIT $3;
                """,
                q_vector_str, chapter_ceiling, k, novel_id
            )
            
        hits = [
            {
                "id": int(r["id"]),
                "chapter": float(r["chapter"]),
                "text": r["text"],
                "score": float(r["score"])
            }
            for r in rows
        ]
        return hits
    except Exception as e:
        logger.error(f"Error during dense search: {e}")
        return []
