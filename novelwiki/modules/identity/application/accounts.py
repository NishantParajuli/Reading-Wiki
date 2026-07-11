from __future__ import annotations

from novelwiki.kernel.errors import Conflict, ValidationFailed
from novelwiki.modules.identity.domain.policies import normalize_username, valid_username


class AccountService:
    def __init__(self, repository):
        self._repository = repository

    async def update_profile(self, user: dict, requested: dict) -> dict:
        fields: dict = {}
        if "display_name" in requested:
            fields["display_name"] = (requested["display_name"] or "").strip()[:80] or None
        if "bio" in requested:
            fields["bio"] = (requested["bio"] or "").strip()[:600] or None
        if "prefs" in requested and isinstance(requested["prefs"], dict):
            fields["prefs"] = requested["prefs"]
        if "username" in requested and requested["username"] is not None:
            username = normalize_username(requested["username"])
            if not valid_username(username):
                raise ValidationFailed("Username must be 3–24 chars: a–z, 0–9, underscore.")
            if username != user["username"]:
                if await self._repository.username_taken(username, int(user["id"])):
                    raise Conflict("That username is already taken.")
                fields["username"] = username
        if not fields:
            return user
        return await self._repository.update_profile(int(user["id"]), fields)

    async def set_avatar(self, user_id: int, relative_path: str) -> None:
        await self._repository.set_avatar(user_id, relative_path)
