from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request

from novelwiki.platform.config import settings

from ...application import IdentitySessionService
from ...application.ports import AuthRuntime, AvatarStorage


async def identity_session_service_dependency() -> IdentitySessionService:
    raise RuntimeError("IdentitySessionService was not wired by the composition root")


async def ai_capability_dependency() -> Callable[[int], Awaitable[dict]]:
    raise RuntimeError("AI capability projection was not wired by the composition root")


async def identity_auth_runtime_dependency() -> AuthRuntime:
    raise RuntimeError("Identity auth runtime was not wired by the composition root")


async def avatar_storage_dependency() -> AvatarStorage:
    raise RuntimeError("Avatar storage was not wired by the composition root")


async def _load_user_by_token(
    token: str,
    service: IdentitySessionService = Depends(identity_session_service_dependency),
) -> dict | None:
    return await service.load_user(token)


async def optional_user(
    request: Request,
    service: IdentitySessionService = Depends(identity_session_service_dependency),
) -> dict | None:
    token = request.cookies.get(settings.SESSION_COOKIE)
    if not token:
        return None
    return await service.load_user(token)


async def current_user(
    request: Request,
    service: IdentitySessionService = Depends(identity_session_service_dependency),
) -> dict:
    user = await optional_user(request, service)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return user


async def require_verified(user: dict = Depends(current_user)) -> dict:
    if not user.get("email_verified"):
        raise HTTPException(status_code=403, detail="Verify your email to use this feature.")
    return user


async def require_admin(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only.")
    return user
