from contextlib import asynccontextmanager
from fastapi import FastAPI
from novelwiki.platform.database import init_db_pool
from novelwiki.modules.identity.adapters.inbound.cookies import set_csrf_cookie
from novelwiki.platform.web.factory import create_web_app

@asynccontextmanager
async def lifespan(app: FastAPI):
    from novelwiki.bootstrap.lifecycle import build_application_lifecycle

    lifecycle = build_application_lifecycle()
    await lifecycle.start()
    try:
        yield
    finally:
        await lifecycle.stop()

app = create_web_app(lifespan=lifespan, seed_csrf_cookie=set_csrf_cookie)

# Bind API endpoints. The auth router is public (login/register); everything else under
# /api requires a logged-in user via a router-level dependency. Handlers that need the
# user object additionally declare `Depends(current_user)` — FastAPI caches it per request.
from fastapi import Depends
from novelwiki.modules.identity.adapters.inbound.http import (
    identity_auth_persistence_dependency,
    router as auth_router,
)
from novelwiki.platform.auth import current_user, require_admin
from novelwiki.modules.identity.adapters.inbound.dependencies import (
    identity_session_service_dependency,
)
from novelwiki.modules.identity.adapters.inbound.account_http import (
    account_service_dependency,
    quota_service_dependency,
    router as identity_account_router,
)
from novelwiki.modules.experience.adapters.inbound.admin_http import (
    experience_admin_commands_dependency,
    identity_admin_service_dependency,
    router as admin_router,
)
from novelwiki.modules.narration.adapters.inbound.http import (
    narration_principal_factory_dependency,
    narration_service_dependency,
    router as tts_router,
)
from novelwiki.modules.experience.adapters.inbound.http import (
    codex_recap_principal_factory_dependency,
    codex_recap_service_dependency,
    router as product_router,
)
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
app.dependency_overrides[codex_recap_service_dependency] = _codex_migration_service
app.dependency_overrides[codex_recap_principal_factory_dependency] = _codex_principal_factory


async def _identity_admin_service():
    from novelwiki.bootstrap.identity_admin import build_identity_admin_service

    return await build_identity_admin_service()


app.dependency_overrides[identity_admin_service_dependency] = _identity_admin_service


async def _experience_admin_commands():
    from novelwiki.bootstrap.experience import build_experience_admin_commands
    return await build_experience_admin_commands()


app.dependency_overrides[
    experience_admin_commands_dependency
] = _experience_admin_commands


async def _experience_projection_service():
    from novelwiki.bootstrap.experience import build_experience_projection_service

    return await build_experience_projection_service()


app.dependency_overrides[
    experience_projection_service_dependency
] = _experience_projection_service


async def _identity_session_service():
    from novelwiki.modules.identity.adapters.outbound.tokens import hash_token
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

from novelwiki.modules.acquisition.adapters.outbound.importer.storage import ensure_dirs
from novelwiki.platform.web.static import mount_platform_surfaces

mount_platform_surfaces(app, ensure_owner_assets=ensure_dirs)
