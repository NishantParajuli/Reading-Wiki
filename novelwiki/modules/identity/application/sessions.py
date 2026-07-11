from __future__ import annotations

from .ports import SessionRepository, TokenHasher


class IdentitySessionService:
    def __init__(self, repository: SessionRepository, hash_token: TokenHasher):
        self._repository = repository
        self._hash_token = hash_token

    async def load_user(self, token: str) -> dict | None:
        if not token:
            return None
        return await self._repository.load_active_user(self._hash_token(token))
