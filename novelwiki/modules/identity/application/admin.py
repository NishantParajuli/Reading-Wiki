from __future__ import annotations

from collections.abc import Callable

from novelwiki.kernel.errors import InvalidOperation, NotFound, ValidationFailed
from novelwiki.kernel.transactions import UnitOfWork

from ..public import IdentityAdminTransactionApi, Principal

USER_STATUSES = frozenset({"active", "suspended", "banned"})
USER_ROLES = frozenset({"user", "admin"})
QUOTA_COLUMNS = (
    "quota_translated_chapters", "quota_ocr_pages",
    "quota_codex_builds", "quota_tts_chapters",
)


class IdentityAdminService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        revoke_ai_jobs: Callable[[int], object],
    ):
        self._uow_factory = uow_factory
        self._revoke_ai_jobs = revoke_ai_jobs

    async def update_user(
        self, user_id: int, fields: dict, administrator: Principal
    ) -> str:
        fields = dict(fields)
        if not fields:
            return "noop"
        if "status" in fields and fields["status"] not in USER_STATUSES:
            raise ValidationFailed(f"status must be one of {sorted(USER_STATUSES)}.")
        if "role" in fields and fields["role"] not in USER_ROLES:
            raise ValidationFailed(f"role must be one of {sorted(USER_ROLES)}.")
        if user_id == administrator.user_id and (
            ("status" in fields and fields["status"] != "active")
            or fields.get("role") == "user"
        ):
            raise InvalidOperation(
                "You can't suspend or demote your own admin account."
            )
        allowed = {"status", "role", *QUOTA_COLUMNS}
        fields = {key: value for key, value in fields.items() if key in allowed}
        if not fields:
            return "noop"
        suspended = fields.get("status") in ("suspended", "banned")
        async with self._uow_factory() as uow:
            identity = uow.transaction.bind(IdentityAdminTransactionApi)
            role = await identity.user_role(user_id)
            if role is None:
                raise NotFound("User not found.")
            if role == "admin" and fields.get("role") == "user":
                if not await identity.other_admin_count(user_id):
                    raise InvalidOperation(
                        "This is the only admin — promote someone else first."
                    )
            await identity.update_user(user_id, fields)
            if suspended:
                await identity.revoke_sessions(user_id)
        if suspended:
            result = self._revoke_ai_jobs(user_id)
            if hasattr(result, "__await__"):
                await result
        return "success"

    async def delete_user(
        self, user_id: int, administrator: Principal
    ) -> None:
        if user_id == administrator.user_id:
            raise InvalidOperation("You can't delete your own account here.")
        async with self._uow_factory() as uow:
            identity = uow.transaction.bind(IdentityAdminTransactionApi)
            role = await identity.user_role(user_id)
            if role is None:
                raise NotFound("User not found.")
            if role == "admin" and not await identity.other_admin_count(user_id):
                raise InvalidOperation("Can't delete the only admin.")
            await identity.delete_user(user_id)
