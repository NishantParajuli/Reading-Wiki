"""Encrypted credentials owned by Acquisition, isolated by requesting user."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken

from novelwiki.kernel.errors import ValidationFailed


class CookieCipher:
    def __init__(self, secret: str):
        self._secret = secret

    def _fernet(self, user_id: int) -> Fernet:
        if not self._secret or self._secret == "dev-insecure-change-me":
            raise ValidationFailed("Configure a private SESSION_SECRET before saving website login cookies.")
        # Bind ciphertext to both this installation and its owning user. Copying a
        # row to a different user cannot turn it into that user's credentials.
        key = hmac.new(self._secret.encode(),
                       f"tideglass:novelpia-cookies:v1:{int(user_id)}".encode(),
                       hashlib.sha256).digest()
        return Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, user_id: int, cookies: list[dict]) -> str:
        data = json.dumps(cookies, separators=(",", ":")).encode()
        return self._fernet(user_id).encrypt(data).decode()

    def decrypt(self, user_id: int, ciphertext: str) -> list[dict]:
        try:
            return json.loads(self._fernet(user_id).decrypt(ciphertext.encode()))
        except (InvalidToken, ValueError, UnicodeError):
            raise ValidationFailed("Saved Novelpia cookies cannot be opened. Replace them in Settings.") from None


class PostgresAccountCookieRepository:
    def __init__(self, pool, cipher: CookieCipher):
        self._pool = pool
        self._cipher = cipher

    async def read(self, user_id: int) -> tuple[list[dict], datetime | None]:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT ciphertext, updated_at FROM acquisition_account_cookies WHERE user_id = $1 AND provider = 'novelpia-global'",
                int(user_id),
            )
        if row is None:
            return [], None
        return self._cipher.decrypt(user_id, row["ciphertext"]), row["updated_at"]

    async def replace(self, user_id: int, cookies: list[dict]) -> datetime:
        ciphertext = self._cipher.encrypt(user_id, cookies)
        async with self._pool.acquire() as connection:
            return await connection.fetchval(
                """INSERT INTO acquisition_account_cookies(user_id, provider, ciphertext)
                   VALUES ($1, 'novelpia-global', $2)
                   ON CONFLICT (user_id, provider) DO UPDATE
                   SET ciphertext = EXCLUDED.ciphertext, updated_at = now()
                   RETURNING updated_at""", int(user_id), ciphertext,
            )

    async def delete(self, user_id: int) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                "DELETE FROM acquisition_account_cookies WHERE user_id = $1 AND provider = 'novelpia-global'",
                int(user_id),
            )
