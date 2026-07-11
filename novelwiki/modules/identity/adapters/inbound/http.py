"""Authentication endpoints, mounted at /api/auth.

  POST /register | /login | /logout         email+password
  GET  /me                                  current user (401 if anonymous)
  GET  /verify?token=...                     email verification preview (redirects to SPA)
  POST /verify                              consumes verification token after user action
  POST /request-reset | /reset               password reset
  GET  /oauth/{provider}/start | /callback   Google/Discord
"""
import datetime as dt
import logging

import re

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator

from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool
from novelwiki.auth import oauth, rate_limit
from novelwiki.auth.deps import current_user
from novelwiki.auth.email import send_verification_email, send_reset_email
from novelwiki.auth.passwords import hash_password, verify_password
from novelwiki.auth.sessions import (
    create_session, revoke_session, revoke_user_sessions,
    set_session_cookie, clear_session_cookie,
)
from novelwiki.auth.tokens import new_token, hash_token, sign, unsign, stamped
from novelwiki.auth.users import (
    self_user_with_capabilities, valid_username, normalize_username, unique_username,
)

logger = logging.getLogger(__name__)
router = APIRouter()

OAUTH_STATE_COOKIE = "tg_oauth"
OAUTH_STATE_TTL = 600          # 10 minutes to complete the round trip
VERIFY_TTL = dt.timedelta(days=2)
RESET_TTL = dt.timedelta(hours=1)


# ── models ────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _check_email(v: str) -> str:
    v = (v or "").strip()
    if not _EMAIL_RE.match(v):
        raise ValueError("Enter a valid email address.")
    return v


class RegisterPayload(BaseModel):
    email: str
    username: str
    password: str = Field(min_length=8, max_length=200)

    _v_email = field_validator("email")(_check_email)


class LoginPayload(BaseModel):
    identifier: str            # email or username
    password: str


class ResetRequestPayload(BaseModel):
    email: str

    _v_email = field_validator("email")(_check_email)


class ResetPayload(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=200)


class VerifyPayload(BaseModel):
    token: str


class ChangePasswordPayload(BaseModel):
    current_password: str | None = None          # required only if a password is already set
    new_password: str = Field(min_length=8, max_length=200)


# ── helpers ───────────────────────────────────────────────────────────────

async def _issue_email_token(conn, user_id: int, kind: str, ttl: dt.timedelta) -> str:
    raw = new_token()
    await conn.execute(
        "INSERT INTO email_tokens (user_id, kind, token_hash, expires_at) VALUES ($1, $2, $3, $4);",
        user_id, kind, hash_token(raw), dt.datetime.now(dt.timezone.utc) + ttl,
    )
    return raw


def _verify_link(token: str) -> str:
    return f"{settings.PUBLIC_BASE_URL}/api/auth/verify?token={token}"


def _reset_link(token: str) -> str:
    return f"{settings.PUBLIC_BASE_URL}/reset?token={token}"


def _limit(limit: int, window_seconds: int) -> rate_limit.RateLimit:
    return rate_limit.RateLimit(limit=limit, window_seconds=window_seconds)


def _login_ip_limit() -> rate_limit.RateLimit:
    return _limit(settings.AUTH_LOGIN_IP_LIMIT, settings.AUTH_LOGIN_WINDOW_SECONDS)


def _login_account_limit() -> rate_limit.RateLimit:
    return _limit(settings.AUTH_LOGIN_ACCOUNT_LIMIT, settings.AUTH_LOGIN_WINDOW_SECONDS)


def _register_ip_limit() -> rate_limit.RateLimit:
    return _limit(settings.AUTH_REGISTER_IP_LIMIT, settings.AUTH_REGISTER_WINDOW_SECONDS)


def _reset_request_ip_limit() -> rate_limit.RateLimit:
    return _limit(settings.AUTH_RESET_REQUEST_IP_LIMIT, settings.AUTH_RESET_REQUEST_WINDOW_SECONDS)


def _reset_request_email_limit() -> rate_limit.RateLimit:
    return _limit(settings.AUTH_RESET_REQUEST_EMAIL_LIMIT, settings.AUTH_RESET_REQUEST_WINDOW_SECONDS)


def _reset_submit_ip_limit() -> rate_limit.RateLimit:
    return _limit(settings.AUTH_RESET_SUBMIT_IP_LIMIT, settings.AUTH_RESET_SUBMIT_WINDOW_SECONDS)


def _reset_submit_token_limit() -> rate_limit.RateLimit:
    return _limit(settings.AUTH_RESET_SUBMIT_TOKEN_LIMIT, settings.AUTH_RESET_SUBMIT_WINDOW_SECONDS)


def _rate_limited(exc: rate_limit.RateLimitExceeded) -> None:
    raise HTTPException(
        status_code=429,
        detail="Too many attempts. Try again later.",
        headers={"Retry-After": str(exc.retry_after)},
    )


def _log_auth_event(event: str, request: Request, scope: str) -> None:
    logger.warning("auth.%s ip=%s scope=%s", event, rate_limit.client_ip(request), scope)


async def _ensure_or_429(conn, key: str, limit: rate_limit.RateLimit, request: Request, scope: str) -> None:
    try:
        await rate_limit.ensure_allowed(conn, key, limit)
    except rate_limit.RateLimitExceeded as exc:
        _log_auth_event("throttle", request, scope)
        _rate_limited(exc)


async def _consume_or_429(conn, key: str, limit: rate_limit.RateLimit, request: Request, scope: str) -> None:
    try:
        await rate_limit.consume(conn, key, limit)
    except rate_limit.RateLimitExceeded as exc:
        _log_auth_event("throttle", request, scope)
        _rate_limited(exc)


async def _consume_silent(conn, key: str, limit: rate_limit.RateLimit, request: Request, scope: str) -> bool:
    try:
        await rate_limit.consume(conn, key, limit)
        return True
    except rate_limit.RateLimitExceeded:
        _log_auth_event("throttle", request, scope)
        return False


# ── email + password ──────────────────────────────────────────────────────

@router.post("/register")
async def register(payload: RegisterPayload, request: Request, response: Response):
    email = payload.email.lower()
    username = normalize_username(payload.username)
    if not valid_username(username):
        raise HTTPException(status_code=422, detail="Username must be 3–24 chars: a–z, 0–9, underscore.")
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        ip_key = rate_limit.bucket_key("auth:register:ip", rate_limit.client_ip(request))
        await _consume_or_429(conn, ip_key, _register_ip_limit(), request, "register:ip")
        pw_hash = hash_password(payload.password)
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO users (email, username, password_hash, display_name)
                VALUES ($1, $2, $3, $4) RETURNING *;
                """,
                email, username, pw_hash, username,
            )
        except asyncpg.UniqueViolationError as e:
            field = "email" if "email" in str(e).lower() else "username"
            raise HTTPException(status_code=409, detail=f"That {field} is already taken.")
        token = await _issue_email_token(conn, row["id"], "verify", VERIFY_TTL)
        session = await create_session(conn, row["id"], request.headers.get("user-agent"))
    await send_verification_email(email, _verify_link(token))
    set_session_cookie(response, session)
    return await self_user_with_capabilities(dict(row))


@router.post("/login")
async def login(payload: LoginPayload, request: Request, response: Response):
    ident = payload.identifier.strip()
    ident_key = ident.lower()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        ip_key = rate_limit.bucket_key("auth:login:ip", rate_limit.client_ip(request))
        account_key = rate_limit.bucket_key("auth:login:account", ident_key)
        await _ensure_or_429(conn, ip_key, _login_ip_limit(), request, "login:ip")
        await _ensure_or_429(conn, account_key, _login_account_limit(), request, "login:account")
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE email = $1 OR username = $2;",
            ident_key, ident_key,
        )
        if row is None or not row["password_hash"] or not verify_password(row["password_hash"], payload.password):
            await _consume_or_429(conn, ip_key, _login_ip_limit(), request, "login:ip")
            await _consume_or_429(conn, account_key, _login_account_limit(), request, "login:account")
            _log_auth_event("failure", request, "login")
            raise HTTPException(status_code=401, detail="Invalid credentials.")
        if row["status"] != "active":
            _log_auth_event("failure", request, "login:status")
            raise HTTPException(status_code=403, detail="This account is suspended.")
        await rate_limit.clear(conn, ip_key)
        await rate_limit.clear(conn, account_key)
        session = await create_session(conn, row["id"], request.headers.get("user-agent"))
    set_session_cookie(response, session)
    return await self_user_with_capabilities(dict(row))


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(settings.SESSION_COOKIE)
    if token:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await revoke_session(conn, token)
    clear_session_cookie(response)
    return {"status": "ok"}


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    return await self_user_with_capabilities(user)


@router.get("/links")
async def oauth_links(user: dict = Depends(current_user)):
    """Which OAuth providers are linked to the signed-in account (account panel)."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT provider FROM oauth_accounts WHERE user_id = $1 ORDER BY provider;", user["id"],
        )
    return {"linked": [r["provider"] for r in rows], "has_password": bool(user.get("password_hash"))}


@router.post("/change-password")
async def change_password(payload: ChangePasswordPayload, request: Request, response: Response,
                          user: dict = Depends(current_user)):
    """Set or change the account password. If one is already set, the current one must match.
    Succeeds for OAuth-only users (no current password) so they can add password login.
    All other sessions are revoked; this device gets a fresh session so it stays signed in."""
    if user.get("password_hash"):
        if not payload.current_password or not verify_password(user["password_hash"], payload.current_password):
            raise HTTPException(status_code=403, detail="Current password is incorrect.")
    new_hash = hash_password(payload.new_password)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET password_hash = $1, updated_at = now() WHERE id = $2;", new_hash, user["id"])
        await revoke_user_sessions(conn, user["id"])
        session = await create_session(conn, user["id"], request.headers.get("user-agent"))
    set_session_cookie(response, session)
    return {"status": "ok"}


@router.get("/verify")
async def verify_email(token: str):
    th = hash_token(token)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        valid = await conn.fetchval(
            """
            SELECT 1
            FROM email_tokens
            WHERE token_hash = $1 AND kind = 'verify' AND used_at IS NULL AND expires_at > now();
            """,
            th,
        )
    dest = f"/verify?token={token}" if valid else "/verify-failed"
    return RedirectResponse(url=dest, status_code=303)


@router.post("/request-reset")
async def request_reset(payload: ResetRequestPayload, request: Request):
    email = payload.email.lower()
    should_issue = True
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        ip_key = rate_limit.bucket_key("auth:reset-request:ip", rate_limit.client_ip(request))
        email_key = rate_limit.bucket_key("auth:reset-request:email", email)
        should_issue = await _consume_silent(conn, ip_key, _reset_request_ip_limit(), request, "reset-request:ip")
        should_issue = (
            await _consume_silent(conn, email_key, _reset_request_email_limit(), request, "reset-request:email")
        ) and should_issue
        row = await conn.fetchrow("SELECT id FROM users WHERE email = $1;", email) if should_issue else None
        token = None
        if row is not None:
            token = await _issue_email_token(conn, row["id"], "reset", RESET_TTL)
    if token is not None:
        await send_reset_email(email, _reset_link(token))
    # Don't reveal whether the email exists.
    return {"status": "ok"}


@router.post("/reset")
async def reset_password(payload: ResetPayload, request: Request, response: Response):
    th = hash_token(payload.token)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        ip_key = rate_limit.bucket_key("auth:reset-submit:ip", rate_limit.client_ip(request))
        token_key = rate_limit.bucket_key("auth:reset-submit:token", th)
        await _consume_or_429(conn, ip_key, _reset_submit_ip_limit(), request, "reset-submit:ip")
        await _consume_or_429(conn, token_key, _reset_submit_token_limit(), request, "reset-submit:token")
        row = await conn.fetchrow(
            """
            UPDATE email_tokens SET used_at = now()
            WHERE token_hash = $1 AND kind = 'reset' AND used_at IS NULL AND expires_at > now()
            RETURNING user_id;
            """,
            th,
        )
        if row is None:
            _log_auth_event("failure", request, "reset-submit")
            raise HTTPException(status_code=400, detail="This reset link is invalid or expired.")
        pw_hash = hash_password(payload.password)
        await conn.execute("UPDATE users SET password_hash = $1 WHERE id = $2;", pw_hash, row["user_id"])
        await revoke_user_sessions(conn, row["user_id"])   # force re-login everywhere
    clear_session_cookie(response)
    return {"status": "ok"}


@router.post("/verify")
async def verify_email_confirm(payload: VerifyPayload):
    th = hash_token(payload.token)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE email_tokens SET used_at = now()
            WHERE token_hash = $1 AND kind = 'verify' AND used_at IS NULL AND expires_at > now()
            RETURNING user_id;
            """,
            th,
        )
        if row is None:
            raise HTTPException(status_code=400, detail="This verification link is invalid or expired.")
        await conn.execute("UPDATE users SET email_verified = TRUE WHERE id = $1;", row["user_id"])
    return {"status": "ok"}


# ── OAuth ─────────────────────────────────────────────────────────────────

@router.get("/providers")
async def providers():
    """Which OAuth buttons the login UI should show."""
    return {"providers": oauth.configured_providers()}


@router.get("/oauth/{provider}/start")
async def oauth_start(provider: str):
    if not oauth.is_configured(provider):
        raise HTTPException(status_code=404, detail="Provider not configured.")
    nonce = new_token(16)
    state = sign(stamped(f"{provider}:{nonce}"))
    resp = RedirectResponse(url=oauth.authorize_url(provider, nonce), status_code=302)
    resp.set_cookie(
        OAUTH_STATE_COOKIE, state, max_age=OAUTH_STATE_TTL,
        httponly=True, secure=settings.COOKIE_SECURE, samesite="lax", path="/",
    )
    return resp


@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, request: Request, code: str | None = None, state: str | None = None):
    if not oauth.is_configured(provider):
        raise HTTPException(status_code=404, detail="Provider not configured.")
    cookie = request.cookies.get(OAUTH_STATE_COOKIE)
    expected = unsign(cookie, max_age=OAUTH_STATE_TTL) if cookie else None
    # expected looks like "<provider>:<nonce>:<ts>"; match provider + the nonce echoed in `state`.
    if not code or not state or expected is None or not expected.startswith(f"{provider}:") \
            or expected.split(":")[1] != state:
        return RedirectResponse(url="/login?error=oauth", status_code=303)

    try:
        identity = await oauth.exchange_code(provider, code)
    except Exception as e:
        logger.warning("OAuth exchange failed for %s: %s", provider, e)
        return RedirectResponse(url="/login?error=oauth", status_code=303)

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            user = await _find_or_create_oauth_user(conn, provider, identity)
            session = await create_session(conn, user["id"], request.headers.get("user-agent"))

    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    set_session_cookie(resp, session)
    return resp


async def _find_or_create_oauth_user(conn, provider: str, identity: dict) -> dict:
    pid = identity["provider_account_id"]
    # 1. Existing link?
    linked = await conn.fetchrow(
        """
        SELECT u.* FROM oauth_accounts oa JOIN users u ON u.id = oa.user_id
        WHERE oa.provider = $1 AND oa.provider_account_id = $2;
        """,
        provider, pid,
    )
    if linked is not None:
        return dict(linked)

    email = identity.get("email")
    email_verified = bool(identity.get("email_verified"))
    # 2. Link to an existing account only when the provider verified the email.
    if email and email_verified:
        existing = await conn.fetchrow("SELECT * FROM users WHERE email = $1;", email)
        if existing is not None:
            await conn.execute(
                "INSERT INTO oauth_accounts (user_id, provider, provider_account_id) VALUES ($1, $2, $3) "
                "ON CONFLICT DO NOTHING;",
                existing["id"], provider, pid,
            )
            return dict(existing)

    # 3. Brand-new user. OAuth email is trusted as verified when the provider says so.
    base = identity.get("name") or (email.split("@")[0] if email else provider + "_user")
    username = await unique_username(conn, base)
    placeholder_email = email if email_verified else f"{username}@{provider}.oauth.local"
    new = await conn.fetchrow(
        """
        INSERT INTO users (email, username, display_name, email_verified, password_hash)
        VALUES ($1, $2, $3, $4, NULL) RETURNING *;
        """,
        placeholder_email, username, identity.get("name") or username, email_verified,
    )
    await conn.execute(
        "INSERT INTO oauth_accounts (user_id, provider, provider_account_id) VALUES ($1, $2, $3);",
        new["id"], provider, pid,
    )
    return dict(new)
