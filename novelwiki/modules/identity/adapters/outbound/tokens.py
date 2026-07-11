"""Opaque token generation, hashing, and HMAC signing.

Two distinct concerns:
  * `new_token` / `hash_token` — random secrets (session + email tokens). We store only
    the SHA-256 hash so a DB leak doesn't expose live tokens.
  * `sign` / `unsign` — tamper-proof short-lived values carried in a cookie (OAuth state),
    keyed by SESSION_SECRET. Not encrypted, just authenticated.
"""
import hashlib
import hmac
import secrets
import time

from novelwiki.platform.config import settings


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sig(value: str) -> str:
    return hmac.new(settings.SESSION_SECRET.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def sign(value: str) -> str:
    """Return `value.signature`."""
    return f"{value}.{_sig(value)}"


def unsign(signed: str, max_age: int | None = None) -> str | None:
    """Verify a `value.signature` string. If `value` ends in `:<unix_ts>` and `max_age`
    is given, also enforce freshness. Returns the value or None."""
    try:
        value, sig = signed.rsplit(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _sig(value)):
        return None
    if max_age is not None:
        try:
            ts = int(value.rsplit(":", 1)[1])
        except (ValueError, IndexError):
            return None
        if time.time() - ts > max_age:
            return None
    return value


def stamped(value: str) -> str:
    """`value:<unix_ts>` — pair with `unsign(..., max_age=...)`."""
    return f"{value}:{int(time.time())}"
