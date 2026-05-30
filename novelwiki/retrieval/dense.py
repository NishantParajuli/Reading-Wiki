import logging
from novelwiki.agent.llm_client import get_embedding
from novelwiki.db.connection import get_db_pool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def dense_search(query: str, chapter_ceiling: float, k: int = 50) -> list[dict]:
    """
    Computes query embedding and performs a pgvector cosine similarity search,
    pre-filtering strictly where chapter <= chapter_ceiling.
    Returns: [{"id": int, "chapter": float, "text": str, "score": float}]
    """
    try:
        # 1. Embed query
        q_vector = await get_embedding(query)
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
                WHERE chapter <= $2 AND embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector
                LIMIT $3;
                """,
                q_vector_str, chapter_ceiling, k
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
