import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from novelwiki.config.settings import settings
from novelwiki.db.connection import init_db_pool, close_db_pool
from novelwiki.db.schema import init_database
from novelwiki.api.routes import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup Phase ──
    logger.info("Ensuring database schema exists...")
    try:
        await init_database()
    except Exception as e:
        logger.warning(f"Schema init at startup failed (continuing): {e}")

    logger.info("Initializing database connection pool...")
    await init_db_pool()

    # BM25 indexes are per-novel and lazy: each novel's index is built/loaded on its
    # first codex query, so there's nothing to preload here.

    # The import worker is a single durable, DB-polled background task: it advances
    # EPUB/PDF ingestion jobs (parse → segment → commit) and resumes ones a restart
    # interrupted. It only touches its own tables, so a failure here can't break reading.
    try:
        from novelwiki.importer.jobs import start_worker
        start_worker()
    except Exception as e:
        logger.warning(f"Could not start the import worker (continuing): {e}")

    yield

    # ── Shutdown Phase ──
    try:
        from novelwiki.importer.jobs import stop_worker
        await stop_worker()
    except Exception as e:
        logger.warning(f"Error stopping import worker: {e}")

    logger.info("Closing database connection pool...")
    await close_db_pool()

app = FastAPI(
    title="Novel Reading Platform",
    description="A multi-novel reading platform with scraping, translation, and a spoiler-safe codex.",
    version="2.0.0",
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

# Serve extracted import assets (covers, illustrations, page scans) + staged preview
# thumbnails under ASSET_DIR. Registered BEFORE the "/" catch-all so it isn't shadowed.
try:
    from novelwiki.importer.storage import ensure_dirs
    ensure_dirs()
    app.mount("/assets", StaticFiles(directory=settings.ASSET_DIR), name="assets")
except Exception as e:
    logger.warning(f"Could not mount /assets static folder: {e}")

# Serve the UI static files (index.html at root).
# IMPORTANT: a Mount at "/" matches every path, so it MUST be registered AFTER
# the API router, /health, and /assets, otherwise it shadows them.
try:
    app.mount("/", StaticFiles(directory="novelwiki/frontend", html=True), name="frontend")
except Exception as e:
    logger.warning(f"Could not mount static frontend folder: {e}")
