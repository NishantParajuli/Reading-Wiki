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

    # Multi-user: bootstrap the admin + reassign any pre-existing single-user data to the
    # shared Global library. Idempotent — a no-op once the DB is already multi-user.
    try:
        from novelwiki.db.migrate_multiuser import maybe_migrate
        await maybe_migrate()
    except Exception as e:
        logger.error(f"Multi-user migration at startup failed: {e}")
        raise

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

# CORS: cookie-based auth requires explicit origins (browsers reject `*` with
# credentials). The SPA is served same-origin in prod; ALLOWED_ORIGINS covers the
# tunnel domain + local dev. Comma-separated in the env var.
_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bind API endpoints. The auth router is public (login/register); everything else under
# /api requires a logged-in user via a router-level dependency. Handlers that need the
# user object additionally declare `Depends(current_user)` — FastAPI caches it per request.
from fastapi import Depends
from novelwiki.auth.router import router as auth_router
from novelwiki.auth.deps import current_user, require_admin
from novelwiki.api.admin_routes import router as admin_router
app.include_router(auth_router, prefix="/api/auth")
app.include_router(router, prefix="/api", dependencies=[Depends(current_user)])
# Admin dashboard — every route gated behind an admin session (require_admin → current_user).
app.include_router(admin_router, prefix="/api/admin", dependencies=[Depends(require_admin)])

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
#
# The SPA ships unbundled .jsx/.js/.css under stable filenames with no content
# hashes, and index.html references them without a ?v= query. Under the default
# StaticFiles headers (ETag/Last-Modified but no Cache-Control) browsers apply
# heuristic caching and may keep a stale api.js across a deploy while loading a
# fresh app.jsx — e.g. an old api.js without `auth` against an app.jsx that calls
# window.API.auth.me(), which throws and blanks the page. `no-cache` keeps the
# files cacheable but forces an ETag revalidation on every load: unchanged files
# still 304 (cheap), and a redeploy is picked up immediately.
class RevalidatingStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response

try:
    app.mount("/", RevalidatingStaticFiles(directory="novelwiki/frontend", html=True), name="frontend")
except Exception as e:
    logger.warning(f"Could not mount static frontend folder: {e}")
