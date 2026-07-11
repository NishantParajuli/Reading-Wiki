"""Argon2id password hashing."""
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """True iff `password` matches `stored_hash`. False for OAuth-only accounts (no hash)."""
    if not stored_hash:
        return False
    try:
        return _ph.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _ph.check_needs_rehash(stored_hash)
    except Exception:
        return False
