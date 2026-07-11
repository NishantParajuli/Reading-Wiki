import os
import json
import asyncio
import logging
import numpy as np
import bm25s
from novelwiki.platform.config import settings
from novelwiki.platform.database import get_db_pool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BM25Manager:
    """
    In-process BM25 lexical search for a SINGLE novel, backed by an index that is
    BUILT ONCE and PERSISTED to disk (settings.BM25_INDEX_PATH/<novel_id>). It is
    rebuilt only when that novel's chunk set changes (see staleness signature),
    never on every query.

    Spoiler-safety (Invariant 7): the chapter ceiling is enforced per query with a
    0/1 ``weight_mask`` so chunks from chapters > ceiling score 0, plus a
    defensive post-filter on the returned hits.
    """

    def __init__(self, novel_id: int):
        self.novel_id = novel_id
        self.corpus: list[dict] = []          # [{"id", "chapter", "text"}], aligned to index order
        self.chapter_arr = np.array([])        # vectorized chapters, aligned to corpus
        self.retriever: bm25s.BM25 | None = None
        self._loaded = False
        # Serializes build/load so two coroutines can't race a rebuild of this novel's index.
        self._lock = asyncio.Lock()
        self.index_dir = os.path.join(settings.BM25_INDEX_PATH, str(novel_id))
        self._meta_path = os.path.join(self.index_dir, "novelwiki_meta.json")

    async def _offload(self, fn, *args):
        """Run a blocking (CPU/disk) BM25 op off the event loop when offload is enabled,
        so tokenization/indexing/search can't stall unrelated requests."""
        if settings.BM25_THREAD_OFFLOAD:
            return await asyncio.to_thread(fn, *args)
        return fn(*args)

    # ── Corpus / metadata ──────────────────────────────────────────────────
    async def _load_corpus_rows(self):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, chapter, text FROM chunks WHERE novel_id = $1 ORDER BY id ASC;",
                self.novel_id,
            )
        self.corpus = [
            {"id": int(r["id"]), "chapter": float(r["chapter"]), "text": r["text"]}
            for r in rows
        ]
        self.chapter_arr = np.array([c["chapter"] for c in self.corpus], dtype=float)
        logger.info(f"Loaded {len(self.corpus)} chunks into BM25 corpus for novel {self.novel_id}.")

    def _db_signature(self) -> dict:
        """Cheap fingerprint of the indexed chunk set, used to detect staleness.

        Chunks are immutable (a re-chunk deletes + reinserts them with fresh BIGSERIAL
        ids), so count + max_id already move whenever content changes; `total_chars` is a
        belt-and-suspenders guard against a coincidental count/max_id match after an edit.
        A codex rebuild additionally calls `rebuild()` explicitly, so the on-disk index is
        never trusted stale.
        """
        return {
            "novel_id": self.novel_id,
            "count": len(self.corpus),
            "max_id": max((c["id"] for c in self.corpus), default=0),
            "total_chars": sum(len(c["text"]) for c in self.corpus),
            "dim": settings.EMBED_DIM,  # not used by BM25 but ties the cache to a build config
        }

    # ── Build / persist / load ─────────────────────────────────────────────
    def _build_retriever(self):
        if not self.corpus:
            self.retriever = None
            return
        texts = [c["text"] for c in self.corpus]
        tokens = bm25s.tokenize(texts, stopwords="english", show_progress=False)
        retriever = bm25s.BM25()
        retriever.index(tokens, show_progress=False)
        self.retriever = retriever

    def _save(self):
        if self.retriever is None:
            return
        os.makedirs(self.index_dir, exist_ok=True)
        self.retriever.save(self.index_dir)
        with open(self._meta_path, "w") as f:
            json.dump(self._db_signature(), f)
        logger.info(f"Persisted BM25 index to {self.index_dir}.")

    def _try_load_from_disk(self) -> bool:
        if not os.path.exists(self._meta_path):
            return False
        try:
            with open(self._meta_path) as f:
                saved = json.load(f)
        except Exception as e:
            logger.warning(f"Could not read BM25 meta: {e}")
            return False
        if saved != self._db_signature():
            logger.info("On-disk BM25 index is stale (chunk set changed); will rebuild.")
            return False
        try:
            self.retriever = bm25s.BM25.load(self.index_dir, load_vocab=True)
            return True
        except Exception as e:
            logger.warning(f"Failed to load BM25 index from disk: {e}; will rebuild.")
            return False

    async def load_or_build_index(self):
        """Load the persisted index if present and fresh, else build+save.

        The tokenize/index/save and disk-load steps are synchronous, so they run off the
        event loop (see `_offload`). Callers hold `self._lock`.
        """
        await self._load_corpus_rows()
        self._loaded = True
        if not self.corpus:
            self.retriever = None
            logger.info(f"No chunks present for novel {self.novel_id}; BM25 index is empty.")
            return
        if await self._offload(self._try_load_from_disk):
            logger.info(f"Loaded persisted BM25 index ({len(self.corpus)} docs) for novel {self.novel_id}.")
            return
        logger.info(f"Building BM25 index over {len(self.corpus)} chunks for novel {self.novel_id}...")
        await self._offload(self._build_retriever)
        await self._offload(self._save)

    async def ensure_loaded(self):
        """Lazy entry point for query paths: build/load the index on first use.
        Double-checked under the lock so concurrent first-queries build only once."""
        if self._loaded:
            return
        async with self._lock:
            if not self._loaded:
                await self.load_or_build_index()

    async def rebuild(self):
        """Force a fresh build + persist (used by `rebuild-bm25` after ingestion)."""
        async with self._lock:
            await self._load_corpus_rows()
            self._loaded = True
            if not self.corpus:
                self.retriever = None
                logger.info(f"No chunks present for novel {self.novel_id}; nothing to index.")
                return
            await self._offload(self._build_retriever)
            await self._offload(self._save)
        logger.info(f"BM25 index rebuilt for novel {self.novel_id}.")

    # ── Query ──────────────────────────────────────────────────────────────
    def search(self, query: str, chapter_ceiling: float, k: int = 50) -> list[dict]:
        if not self.corpus or self.retriever is None:
            return []

        # Mask future chapters to a 0 weight (Invariant 7).
        mask = (self.chapter_arr <= chapter_ceiling).astype(np.float32)
        if not mask.any():
            logger.info(f"No chunks at/below chapter ceiling {chapter_ceiling}.")
            return []

        top_k = min(k, len(self.corpus))
        if top_k <= 0:
            return []

        try:
            query_tokens = bm25s.tokenize(
                [query], stopwords="english", return_ids=False, show_progress=False
            )
            results, scores = self.retriever.retrieve(
                query_tokens, k=top_k, weight_mask=mask, show_progress=False
            )
        except Exception as e:
            logger.error(f"Error during BM25 retrieve: {e}")
            return []

        hits = []
        for doc_idx, score in zip(results[0], scores[0]):
            if score <= 0:
                continue  # masked future chapter or non-match
            doc = self.corpus[int(doc_idx)]
            if doc["chapter"] > chapter_ceiling:  # defense-in-depth
                continue
            hits.append({
                "id": doc["id"],
                "chapter": doc["chapter"],
                "text": doc["text"],
                "score": float(score),
            })
        return hits

    async def asearch(self, query: str, chapter_ceiling: float, k: int = 50) -> list[dict]:
        """Async wrapper around `search` that runs the blocking tokenize/retrieve off the
        event loop (when offload is enabled). Query paths should call this, not `search`."""
        return await self._offload(self.search, query, chapter_ceiling, k)


# ── Per-novel manager registry ───────────────────────────────────────────
# Indexes are lazy: a novel's manager is created and loaded on first use, so the
# app doesn't pay to load every novel's index at startup.
_managers: dict[int, BM25Manager] = {}


def get_bm25_manager(novel_id: int) -> BM25Manager:
    m = _managers.get(novel_id)
    if m is None:
        m = BM25Manager(novel_id)
        _managers[novel_id] = m
    return m
