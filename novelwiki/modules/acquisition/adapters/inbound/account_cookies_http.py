"""Settings routes never return, echo, or log cookie values."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from novelwiki.kernel.errors import ValidationFailed
from novelwiki.platform.auth import current_user

from ...application.account_cookies import AccountCookieService
from ...domain.account_cookies import MAX_EXPORT_BYTES

router = APIRouter()


async def account_cookie_service_dependency() -> AccountCookieService:
    raise RuntimeError("AccountCookieService was not wired by the composition root")


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("/settings/novelpia-cookies")
async def cookie_status(
    response: Response,
    user: dict = Depends(current_user),
    service: AccountCookieService = Depends(account_cookie_service_dependency),
):
    _private(response)
    try:
        return await service.status(int(user["id"]))
    except ValidationFailed as exc:
        raise HTTPException(422, str(exc), headers={"Cache-Control": "no-store"}) from None


@router.put("/settings/novelpia-cookies", openapi_extra={
    "requestBody": {"required": True, "content": {"application/json": {"schema": {
        "type": "object", "required": ["cookies"], "properties": {
            "cookies": {"type": "array", "items": {"type": "object"},
                        "description": "EditThisCookie JSON export; credential values are write-only."}
        }
    }}}}
})
async def replace_cookies(
    request: Request,
    response: Response,
    user: dict = Depends(current_user),
    service: AccountCookieService = Depends(account_cookie_service_dependency),
):
    _private(response)
    # Do not let normal validation errors echo secret-bearing request bodies.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_EXPORT_BYTES:
            raise HTTPException(413, "Cookie export is too large (maximum 64 KiB).",
                                headers={"Cache-Control": "no-store"})
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict) or set(payload) != {"cookies"}:
            raise ValueError
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(422, "Send a JSON object containing the cookies export.",
                            headers={"Cache-Control": "no-store"}) from None
    try:
        return await service.replace(int(user["id"]), payload["cookies"])
    except ValidationFailed as exc:
        raise HTTPException(422, str(exc), headers={"Cache-Control": "no-store"}) from None


@router.delete("/settings/novelpia-cookies")
async def delete_cookies(
    response: Response,
    user: dict = Depends(current_user),
    service: AccountCookieService = Depends(account_cookie_service_dependency),
):
    _private(response)
    return await service.delete(int(user["id"]))
