from contextlib import asynccontextmanager
from fastapi import FastAPI
from novelwiki.platform.database import init_db_pool
from novelwiki.modules.identity.adapters.inbound.cookies import set_csrf_cookie
from novelwiki.modules.identity.adapters.outbound.tokens import new_token
from novelwiki.platform.observability.logging import configure_logging
from novelwiki.platform.web.factory import create_web_app

configure_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    from novelwiki.bootstrap.lifecycle import build_application_lifecycle

    lifecycle = build_application_lifecycle()
    await lifecycle.start()
    try:
        yield
    finally:
        await lifecycle.stop()

app = create_web_app(
    lifespan=lifespan,
    seed_csrf_cookie=lambda response: set_csrf_cookie(response, new_token()),
)

# Bind API endpoints. The auth router is public (login/register); everything else under
# /api requires a logged-in user via a router-level dependency. Handlers that need the
# user object additionally declare `Depends(current_user)` — FastAPI caches it per request.
from fastapi import Depends
from novelwiki.modules.identity.adapters.inbound.http import (
    configure_email_delivery,
    identity_auth_persistence_dependency,
    router as auth_router,
)
from novelwiki.modules.identity.adapters.outbound.email import (
    send_reset_email,
    send_verification_email,
)

configure_email_delivery(send_verification_email, send_reset_email)
from novelwiki.platform.auth import current_user, require_admin
from novelwiki.modules.identity.adapters.inbound.dependencies import (
    ai_capability_dependency,
    avatar_storage_dependency,
    identity_auth_runtime_dependency,
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
    catalog_read_access_dependency,
    codex_recap_principal_factory_dependency,
    codex_recap_service_dependency,
    narration_coverage_dependency,
    router as product_router,
)
from novelwiki.modules.reading.adapters.inbound.http import (
    reading_migration_service_dependency,
    reading_service_dependency,
    router as reading_router,
)
from novelwiki.modules.work.adapters.inbound.http import (
    router as work_router,
    work_service_dependency,
)
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
from novelwiki.modules.experience.adapters.inbound.dependencies import (
    operational_projection_dependency,
    quota_projection_dependency,
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


async def _narration_coverage():
    from novelwiki.bootstrap.narration import build_narration_queries
    return await build_narration_queries()


app.dependency_overrides[narration_coverage_dependency] = _narration_coverage


async def _experience_catalog_access():
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import CatalogAccessService

    pool = await init_db_pool()
    async with pool.acquire() as connection:
        yield CatalogAccessService(PostgresCatalogRepository(connection))


app.dependency_overrides[catalog_read_access_dependency] = _experience_catalog_access


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


async def _ai_capability():
    from novelwiki.modules.ai_execution.adapters.outbound.policy import capability_for_user

    return capability_for_user


app.dependency_overrides[ai_capability_dependency] = _ai_capability


async def _identity_auth_runtime():
    from types import SimpleNamespace

    from novelwiki.modules.identity.adapters.outbound import oauth
    from novelwiki.modules.identity.adapters.outbound.email import (
        send_reset_email,
        send_verification_email,
    )
    from novelwiki.modules.identity.adapters.outbound.passwords import (
        hash_password,
        verify_password,
    )
    from novelwiki.modules.identity.adapters.outbound.tokens import (
        hash_token,
        new_token,
        sign,
        stamped,
        unsign,
    )

    return SimpleNamespace(
        authorize_url=oauth.authorize_url,
        configured_providers=oauth.configured_providers,
        exchange_code=oauth.exchange_code,
        hash_password=hash_password,
        hash_token=hash_token,
        is_provider_configured=oauth.is_configured,
        new_token=new_token,
        send_reset_email=send_reset_email,
        send_verification_email=send_verification_email,
        sign=sign,
        stamped=stamped,
        unsign=unsign,
        verify_password=verify_password,
    )


async def _avatar_storage():
    from novelwiki.modules.identity.adapters.outbound.avatars import AvatarFilesystem
    from novelwiki.platform.config import settings

    return AvatarFilesystem(settings.ASSET_DIR)


app.dependency_overrides[identity_auth_runtime_dependency] = _identity_auth_runtime
app.dependency_overrides[avatar_storage_dependency] = _avatar_storage


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


async def _work_service():
    from novelwiki.bootstrap.work import build_work_service

    return await build_work_service()


app.dependency_overrides[work_service_dependency] = _work_service


async def _operational_projection_repository():
    from novelwiki.bootstrap.experience import build_operational_projection_repository
    return await build_operational_projection_repository()


app.dependency_overrides[
    operational_projection_dependency
] = _operational_projection_repository


async def _quota_projection():
    from types import SimpleNamespace

    from novelwiki.modules.identity.adapters.inbound.presentation import quota_limits
    from novelwiki.modules.identity.adapters.outbound import quota_compat

    return SimpleNamespace(
        is_exempt=quota_compat.is_exempt,
        quota_limits=quota_limits,
        remaining=quota_compat.remaining,
        spend_allowed=quota_compat.spend_allowed,
    )


app.dependency_overrides[quota_projection_dependency] = _quota_projection


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
