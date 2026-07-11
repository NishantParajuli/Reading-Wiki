import logging
import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from novelwiki.platform.config import settings
from novelwiki.platform.database import init_db_pool, close_db_pool
from novelwiki.db.schema import init_database
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

    # The generic jobs worker is a third durable, DB-polled task: it advances scrape / codex-build
    # / translation jobs that used to run in fire-and-forget BackgroundTasks (and would be lost on
    # a deploy after quota was reserved). It reserves/refunds quota explicitly and retries failures.
    try:
        from novelwiki.jobs.worker import start_worker as start_jobs_worker
        start_jobs_worker()
    except Exception as e:
        logger.warning(f"Could not start the jobs worker (continuing): {e}")

    # AGY is intentionally NOT started by the web lifespan. Warn clearly when the
    # rollout switch is on but the separately authenticated host worker is absent.
    if settings.AGY_ENABLED:
        try:
            from novelwiki.ai_backend.policy import worker_available
            if not await worker_available():
                logger.warning(
                    "AGY_ENABLED is true, but no recent healthy dedicated AGY worker heartbeat exists. "
                    "AGY jobs may remain queued until the host worker recovers."
                )
        except Exception as e:
            logger.warning(f"Could not check dedicated AGY worker health: {e}")

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

    try:
        from novelwiki.jobs.worker import stop_worker as stop_jobs_worker
        await stop_jobs_worker()
    except Exception as e:
        logger.warning(f"Error stopping jobs worker: {e}")

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

# The SPA is a precompiled Vite bundle served same-origin: no CDN scripts, no
# eval (Babel Standalone is gone), fonts self-hosted. 'unsafe-inline' remains
# only for the tiny theme-bootstrap script in index.html and inline styles.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; "
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


_REQUEST_ID_HEADER = "X-Request-ID"


@app.middleware("http")
async def security_headers(request, call_next):
    # Correlation id: accept a caller-supplied X-Request-ID (trusted proxy) or mint one, stash it
    # in a contextvar for the duration of the request so logs + audit rows can reference it, and
    # echo it back on the response for client-side/debug correlation.
    from novelwiki.platform.observability import audit
    incoming = request.headers.get(_REQUEST_ID_HEADER, "").strip()
    request_id = incoming[:64] if incoming else audit.new_request_id()
    token = audit.set_request_id(request_id)
    try:
        response = _csrf_rejection(request)
        if response is None:
            response = await call_next(request)
    finally:
        audit.reset_request_id(token)
    response.headers[_REQUEST_ID_HEADER] = request_id
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
from novelwiki.modules.identity.adapters.inbound.http import router as auth_router
from novelwiki.auth.deps import current_user, require_admin
from novelwiki.modules.identity.adapters.inbound.dependencies import (
    identity_session_service_dependency,
)
from novelwiki.modules.identity.adapters.inbound.account_http import (
    account_service_dependency,
    quota_service_dependency,
    router as identity_account_router,
)
from novelwiki.modules.experience.adapters.inbound.admin_http import router as admin_router
from novelwiki.modules.narration.adapters.inbound.http import router as tts_router
from novelwiki.modules.experience.adapters.inbound.http import router as product_router
from novelwiki.modules.reading.adapters.inbound.http import (
    reading_service_dependency,
    router as reading_router,
)
from novelwiki.modules.work.adapters.inbound.http import router as work_router
from novelwiki.modules.catalog.adapters.inbound.http import (
    catalog_migration_service_dependency,
    catalog_service_dependency,
    router as catalog_router,
)
from novelwiki.modules.identity.adapters.inbound.legacy_http import (
    router as legacy_identity_router,
)
from novelwiki.modules.catalog.adapters.inbound.legacy_http import (
    router as legacy_catalog_router,
)
from novelwiki.modules.reading.adapters.inbound.legacy_http import (
    router as legacy_reading_router,
)
from novelwiki.modules.acquisition.adapters.inbound.legacy_http import (
    router as legacy_acquisition_router,
)
from novelwiki.modules.acquisition.adapters.inbound.http import (
    adapter_catalog_dependency,
    router as acquisition_router,
)
from novelwiki.modules.translation.adapters.inbound.legacy_http import (
    router as legacy_translation_router,
)
from novelwiki.modules.codex.adapters.inbound.legacy_http import (
    router as legacy_codex_router,
)
from novelwiki.modules.translation.adapters.inbound.http import (
    glossary_service_dependency,
    principal_factory_dependency,
    router as translation_router,
    translation_scheduling_service_dependency,
)
from novelwiki.modules.experience.adapters.inbound.legacy_http import (
    router as legacy_experience_router,
)
from novelwiki.modules.experience.adapters.inbound.projections_http import (
    experience_projection_service_dependency,
    router as experience_projection_router,
)
app.include_router(auth_router, prefix="/api/auth")
for module_router in (
    legacy_experience_router,
    legacy_catalog_router,
    legacy_identity_router,
    legacy_acquisition_router,
    legacy_reading_router,
    legacy_translation_router,
    legacy_codex_router,
):
    app.include_router(
        module_router, prefix="/api", dependencies=[Depends(current_user)]
    )
app.include_router(reading_router, prefix="/api", dependencies=[Depends(current_user)])
app.include_router(work_router, prefix="/api", dependencies=[Depends(current_user)])
app.include_router(catalog_router, prefix="/api", dependencies=[Depends(current_user)])
app.include_router(acquisition_router, prefix="/api", dependencies=[Depends(current_user)])
app.include_router(experience_projection_router, prefix="/api", dependencies=[Depends(current_user)])
app.include_router(translation_router, prefix="/api", dependencies=[Depends(current_user)])
app.include_router(identity_account_router, prefix="/api", dependencies=[Depends(current_user)])
# Audiobook TTS endpoints (same auth model as the main router).
app.include_router(tts_router, prefix="/api", dependencies=[Depends(current_user)])
# Batch 9 product surfaces: home/activity/health/cost-estimate/recap (same auth model).
app.include_router(product_router, prefix="/api", dependencies=[Depends(current_user)])
# Admin dashboard — every route gated behind an admin session (require_admin → current_user).
app.include_router(admin_router, prefix="/api/admin", dependencies=[Depends(require_admin)])


async def _reading_service():
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import CatalogAccessService
    from novelwiki.modules.reading.adapters.outbound.postgres import PostgresReadingRepository
    from novelwiki.modules.reading.application import ReadingService

    pool = await init_db_pool()
    async with pool.acquire() as connection:
        yield ReadingService(
            PostgresReadingRepository(connection),
            CatalogAccessService(PostgresCatalogRepository(connection)),
        )


app.dependency_overrides[reading_service_dependency] = _reading_service


async def _catalog_service():
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import CatalogAccessService

    pool = await init_db_pool()
    async with pool.acquire() as connection:
        yield CatalogAccessService(PostgresCatalogRepository(connection))


app.dependency_overrides[catalog_service_dependency] = _catalog_service


async def _catalog_migration_service():
    from novelwiki.bootstrap.catalog import build_catalog_migration_service

    return await build_catalog_migration_service()


app.dependency_overrides[
    catalog_migration_service_dependency
] = _catalog_migration_service


async def _glossary_service():
    from novelwiki.bootstrap.translation import build_glossary_service

    return await build_glossary_service()


app.dependency_overrides[glossary_service_dependency] = _glossary_service


async def _translation_scheduling_service():
    from novelwiki.bootstrap.translation import build_translation_scheduling_service

    return await build_translation_scheduling_service()


app.dependency_overrides[
    translation_scheduling_service_dependency
] = _translation_scheduling_service


async def _principal_factory():
    from novelwiki.modules.identity.adapters.principals import principal_from_user

    return principal_from_user


app.dependency_overrides[principal_factory_dependency] = _principal_factory


async def _adapter_catalog_query():
    from novelwiki.bootstrap.acquisition import build_adapter_catalog_query

    return build_adapter_catalog_query()


app.dependency_overrides[adapter_catalog_dependency] = _adapter_catalog_query


async def _experience_projection_service():
    from novelwiki.bootstrap.experience import build_experience_projection_service

    return await build_experience_projection_service()


app.dependency_overrides[
    experience_projection_service_dependency
] = _experience_projection_service


async def _identity_session_service():
    from novelwiki.auth.tokens import hash_token
    from novelwiki.modules.identity.adapters.outbound.postgres_sessions import (
        PostgresSessionRepository,
    )
    from novelwiki.modules.identity.application import IdentitySessionService

    pool = await init_db_pool()
    return IdentitySessionService(PostgresSessionRepository(pool), hash_token)


app.dependency_overrides[
    identity_session_service_dependency
] = _identity_session_service


async def _quota_service():
    from novelwiki.modules.identity.adapters.outbound.postgres_quota import (
        PostgresQuotaRepository,
    )
    from novelwiki.modules.identity.application import QuotaService

    pool = await init_db_pool()
    return QuotaService(PostgresQuotaRepository(pool=pool))


app.dependency_overrides[quota_service_dependency] = _quota_service


async def _account_service():
    from novelwiki.modules.identity.adapters.outbound.postgres_accounts import PostgresAccountRepository
    from novelwiki.modules.identity.application import AccountService

    pool = await init_db_pool()
    async with pool.acquire() as connection:
        yield AccountService(PostgresAccountRepository(connection))


app.dependency_overrides[account_service_dependency] = _account_service

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

# Serve the built SPA (Vite output in frontend/dist).
# IMPORTANT: a Mount at "/" matches every path, so it MUST be registered AFTER
# the API router, /health, and /assets/_users, otherwise it shadows them.
#
# Cache policy: Vite emits content-hashed filenames under /assets/, so those are
# immutable (max-age=1y); index.html (and the handful of unhashed public files:
# favicon, manifest) revalidate on every load so a deploy is picked up
# immediately. Unknown extension-less paths fall back to index.html so
# BrowserRouter deep links (/n/12/read/512) survive a hard refresh.
class SpaStaticFiles(StaticFiles):
    def file_response(self, full_path, *args, **kwargs):
        response = super().file_response(full_path, *args, **kwargs)
        if "/assets/" in str(full_path).replace("\\", "/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response

    async def get_response(self, path: str, scope):
        from starlette.exceptions import HTTPException as StarletteHTTPException
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            # SPA fallback: route-shaped paths (no file extension) get index.html;
            # genuinely missing files still 404.
            last = path.rsplit("/", 1)[-1]
            if e.status_code == 404 and "." not in last:
                return await super().get_response("index.html", scope)
            raise

try:
    app.mount("/", SpaStaticFiles(directory="novelwiki/frontend/dist", html=True), name="frontend")
except Exception as e:
    logger.warning(f"Could not mount static frontend folder (run `npm run build` in novelwiki/frontend): {e}")
