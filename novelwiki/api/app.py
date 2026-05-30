import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from novelwiki.db.connection import init_db_pool, close_db_pool
from novelwiki.retrieval.bm25 import bm25_manager
from novelwiki.api.routes import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup Phase ──
    logger.info("Initializing database connection pool...")
    await init_db_pool()

    logger.info("Loading BM25 lexical search index (from disk if present)...")
    try:
        await bm25_manager.load_or_build_index()
    except Exception as e:
        logger.warning(f"Could not load BM25 index at startup (database might be empty): {e}")

    yield

    # ── Shutdown Phase ──
    logger.info("Closing database connection pool...")
    await close_db_pool()

app = FastAPI(
    title="Spoiler-Aware Webnovel Wiki",
    description="A complete spoiler-gated hybrid-search knowledge base & chat for webnovels.",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for local development and premium UI interactions
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bind API endpoints
app.include_router(router, prefix="/api")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "novelwiki-backend"}

# Serve the UI static files (index.html at root).
# IMPORTANT: a Mount at "/" matches every path, so it MUST be registered AFTER
# the API router and /health, otherwise it shadows them.
try:
    app.mount("/", StaticFiles(directory="novelwiki/frontend", html=True), name="frontend")
except Exception as e:
    logger.warning(f"Could not mount static frontend folder: {e}")
