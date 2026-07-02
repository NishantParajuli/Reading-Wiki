import logging
import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from novelwiki.config.settings import settings
from novelwiki.db.connection import init_db_pool, close_db_pool
from novelwiki.db.schema import init_database
from novelwiki.api.routes import router
from novelwiki.auth.sessions import set_csrf_cookie

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
    pool = await init_db_pool()

    try:
        from novelwiki.auth import rate_limit as auth_rate_limit
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM sessions WHERE expires_at <= now();")
            await conn.execute("DELETE FROM email_tokens WHERE used_at IS NOT NULL OR expires_at <= now();")
            await auth_rate_limit.cleanup(conn)
    except Exception as e:
        logger.warning(f"Auth cleanup at startup failed (continuing): {e}")

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

    # The TTS worker is a second durable, DB-polled background task: it advances audiobook
    # narration jobs (resolve text → narrate via the GPU sidecar → cache Opus) and resumes
    # ones a restart interrupted. Like the import worker it only touches its own tables.
    try:
        from novelwiki.tts.worker import start_worker as start_tts_worker
        start_tts_worker()
    except Exception as e:
        logger.warning(f"Could not start the TTS worker (continuing): {e}")

    yield

    # ── Shutdown Phase ──
    try:
        from novelwiki.importer.jobs import stop_worker
        await stop_worker()
    except Exception as e:
        logger.warning(f"Error stopping import worker: {e}")

    try:
        from novelwiki.tts.worker import stop_worker as stop_tts_worker
        await stop_tts_worker()
    except Exception as e:
        logger.warning(f"Error stopping TTS worker: {e}")

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

_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com; "
    "script-src-elem 'self' 'unsafe-inline' https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
_PUBLIC_AUTH_MUTATIONS = {
    "/api/auth/register",
    "/api/auth/login",
    "/api/auth/request-reset",
    "/api/auth/reset",
    "/api/auth/verify",
}
_REQUEST_HEADER = "x-tideglass-request"
_CSRF_HEADERS = ("x-tideglass-csrf", "x-csrf-token")


def _normalized_path(path: str) -> str:
    stripped = path.rstrip("/")
    return stripped or "/"


def _csrf_rejection(request):
    method = request.method.upper()
    if method in _SAFE_METHODS or not request.url.path.startswith("/api"):
        return None

    path = _normalized_path(request.url.path)
    if path in _PUBLIC_AUTH_MUTATIONS:
        if request.headers.get(_REQUEST_HEADER) == "1":
            return None
        return JSONResponse(
            {"detail": "Missing required request header."},
            status_code=403,
        )

    cookie = request.cookies.get(settings.CSRF_COOKIE)
    supplied = None
    for name in _CSRF_HEADERS:
        supplied = request.headers.get(name)
        if supplied:
            break
    if cookie and supplied and hmac.compare_digest(cookie, supplied):
        return None
    return JSONResponse(
        {"detail": "CSRF token missing or invalid."},
        status_code=403,
    )


def _maybe_seed_csrf_cookie(request, response) -> None:
    if request.cookies.get(settings.SESSION_COOKIE) and not request.cookies.get(settings.CSRF_COOKIE):
        set_csrf_cookie(response)


@app.middleware("http")
async def security_headers(request, call_next):
    response = _csrf_rejection(request)
    if response is None:
        response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Content-Security-Policy", _CSP)
    _maybe_seed_csrf_cookie(request, response)
    return response

# Bind API endpoints. The auth router is public (login/register); everything else under
# /api requires a logged-in user via a router-level dependency. Handlers that need the
# user object additionally declare `Depends(current_user)` — FastAPI caches it per request.
from fastapi import Depends
from novelwiki.auth.router import router as auth_router
from novelwiki.auth.deps import current_user, require_admin
from novelwiki.api.admin_routes import router as admin_router
from novelwiki.api.routes_tts import router as tts_router
app.include_router(auth_router, prefix="/api/auth")
app.include_router(router, prefix="/api", dependencies=[Depends(current_user)])
# Audiobook TTS endpoints (same auth model as the main router).
app.include_router(tts_router, prefix="/api", dependencies=[Depends(current_user)])
# Admin dashboard — every route gated behind an admin session (require_admin → current_user).
app.include_router(admin_router, prefix="/api/admin", dependencies=[Depends(require_admin)])

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "novelwiki-backend"}

# User avatars are intentionally public profile assets; imported novel/job assets are
# served by authenticated /api/assets/... routes instead of this static mount.
try:
    from novelwiki.importer.storage import ensure_dirs
    ensure_dirs()
    avatar_dir = Path(settings.ASSET_DIR) / "_users"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/assets/_users", StaticFiles(directory=str(avatar_dir)), name="user-assets")
except Exception as e:
    logger.warning(f"Could not mount public avatar assets folder: {e}")

# Serve the UI static files (index.html at root).
# IMPORTANT: a Mount at "/" matches every path, so it MUST be registered AFTER
# the API router, /health, and /assets/_users, otherwise it shadows them.
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
