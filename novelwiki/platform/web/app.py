import logging
import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from novelwiki.platform.config import settings
from novelwiki.platform.database import init_db_pool
from novelwiki.auth.sessions import set_csrf_cookie

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    from novelwiki.bootstrap.lifecycle import build_application_lifecycle

    lifecycle = build_application_lifecycle()
    await lifecycle.start()
    try:
        yield
    finally:
        await lifecycle.stop()

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
from novelwiki.modules.identity.adapters.inbound.http import (
    identity_auth_persistence_dependency,
    router as auth_router,
)
from novelwiki.auth.deps import current_user, require_admin
from novelwiki.modules.identity.adapters.inbound.dependencies import (
    identity_session_service_dependency,
)
from novelwiki.modules.identity.adapters.inbound.account_http import (
    account_service_dependency,
    quota_service_dependency,
    router as identity_account_router,
)
from novelwiki.modules.experience.adapters.inbound.admin_http import (
    identity_admin_service_dependency,
    router as admin_router,
)
from novelwiki.modules.narration.adapters.inbound.http import (
    narration_principal_factory_dependency,
    narration_service_dependency,
    router as tts_router,
)
from novelwiki.modules.experience.adapters.inbound.http import router as product_router
from novelwiki.modules.reading.adapters.inbound.http import (
    reading_migration_service_dependency,
    reading_service_dependency,
    router as reading_router,
)
from novelwiki.modules.work.adapters.inbound.http import router as work_router
from novelwiki.modules.catalog.adapters.inbound.http import (
    catalog_migration_service_dependency,
    catalog_service_dependency,
    router as catalog_router,
)
from novelwiki.modules.acquisition.adapters.inbound.http import (
    acquisition_principal_factory_dependency,
    acquisition_service_dependency,
    adapter_catalog_dependency,
    import_service_dependency,
    router as acquisition_router,
)
from novelwiki.modules.codex.adapters.inbound.http import (
    codex_migration_service_dependency,
    codex_principal_factory_dependency,
    router as codex_router,
)
from novelwiki.modules.translation.adapters.inbound.http import (
    glossary_service_dependency,
    principal_factory_dependency,
    router as translation_router,
    translation_scheduling_service_dependency,
)
from novelwiki.modules.experience.adapters.inbound.projections_http import (
    experience_projection_service_dependency,
    router as experience_projection_router,
)
app.include_router(auth_router, prefix="/api/auth")
app.include_router(reading_router, prefix="/api", dependencies=[Depends(current_user)])
app.include_router(work_router, prefix="/api", dependencies=[Depends(current_user)])
app.include_router(catalog_router, prefix="/api", dependencies=[Depends(current_user)])
app.include_router(acquisition_router, prefix="/api", dependencies=[Depends(current_user)])
app.include_router(experience_projection_router, prefix="/api", dependencies=[Depends(current_user)])
app.include_router(codex_router, prefix="/api", dependencies=[Depends(current_user)])
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


async def _reading_migration_service():
    from novelwiki.bootstrap.reading_migration import build_reading_migration_service

    return await build_reading_migration_service()


app.dependency_overrides[
    reading_migration_service_dependency
] = _reading_migration_service


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


async def _acquisition_service():
    from novelwiki.bootstrap.acquisition_routes import build_acquisition_service

    return await build_acquisition_service()


app.dependency_overrides[acquisition_service_dependency] = _acquisition_service


async def _import_service():
    from novelwiki.bootstrap.acquisition_routes import build_import_service
    return await build_import_service()


async def _acquisition_principal_factory():
    from novelwiki.bootstrap.acquisition_routes import (
        build_acquisition_principal_factory,
    )
    return build_acquisition_principal_factory()


app.dependency_overrides[import_service_dependency] = _import_service
app.dependency_overrides[
    acquisition_principal_factory_dependency
] = _acquisition_principal_factory


async def _codex_migration_service():
    from novelwiki.bootstrap.codex_migration import build_codex_migration_service

    return await build_codex_migration_service()


async def _codex_principal_factory():
    from novelwiki.bootstrap.codex_migration import build_codex_principal_factory

    return await build_codex_principal_factory()


app.dependency_overrides[codex_migration_service_dependency] = _codex_migration_service
app.dependency_overrides[codex_principal_factory_dependency] = _codex_principal_factory


async def _identity_admin_service():
    from novelwiki.bootstrap.identity_admin import build_identity_admin_service

    return await build_identity_admin_service()


app.dependency_overrides[identity_admin_service_dependency] = _identity_admin_service


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


async def _identity_auth_persistence():
    from novelwiki.modules.identity.adapters.outbound.postgres_auth import (
        PostgresAuthPersistence,
    )

    pool = await init_db_pool()
    return PostgresAuthPersistence(pool)


app.dependency_overrides[
    identity_auth_persistence_dependency
] = _identity_auth_persistence


async def _narration_service():
    from novelwiki.bootstrap.narration import build_narration_service
    return await build_narration_service()


async def _narration_principal_factory():
    from novelwiki.bootstrap.narration import build_narration_principal_factory
    return build_narration_principal_factory()


app.dependency_overrides[narration_service_dependency] = _narration_service
app.dependency_overrides[
    narration_principal_factory_dependency
] = _narration_principal_factory

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
