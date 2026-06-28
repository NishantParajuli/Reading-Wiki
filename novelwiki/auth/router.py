"""Authentication endpoints, mounted at /api/auth.

  POST /register | /login | /logout         email+password
  GET  /me                                  current user (401 if anonymous)
  GET  /verify?token=...                     email verification (redirects to SPA)
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
from novelwiki.auth import oauth
from novelwiki.auth.deps import current_user
from novelwiki.auth.email import send_verification_email, send_reset_email
from novelwiki.auth.passwords import hash_password, verify_password
from novelwiki.auth.sessions import (
    create_session, revoke_session, revoke_user_sessions,
    set_session_cookie, clear_session_cookie,
)
from novelwiki.auth.tokens import new_token, hash_token, sign, unsign, stamped
from novelwiki.auth.users import (
    self_user, valid_username, normalize_username, unique_username,
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
    return f"{settings.PUBLIC_BASE_URL}/#/reset?token={token}"


# ── email + password ──────────────────────────────────────────────────────

@router.post("/register")
async def register(payload: RegisterPayload, request: Request, response: Response):
    email = payload.email.lower()
    username = normalize_username(payload.username)
    if not valid_username(username):
        raise HTTPException(status_code=422, detail="Username must be 3–24 chars: a–z, 0–9, underscore.")
    pw_hash = hash_password(payload.password)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
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
    return self_user(dict(row))


@router.post("/login")
async def login(payload: LoginPayload, request: Request, response: Response):
    ident = payload.identifier.strip()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE email = $1 OR username = $2;",
            ident.lower(), ident,
        )
        if row is None or not verify_password(row["password_hash"], payload.password):
            raise HTTPException(status_code=401, detail="Invalid credentials.")
        if row["status"] != "active":
            raise HTTPException(status_code=403, detail="This account is suspended.")
        session = await create_session(conn, row["id"], request.headers.get("user-agent"))
    set_session_cookie(response, session)
    return self_user(dict(row))


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
    return self_user(user)


@router.get("/verify")
async def verify_email(token: str):
    th = hash_token(token)
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
        if row is not None:
            await conn.execute("UPDATE users SET email_verified = TRUE WHERE id = $1;", row["user_id"])
    # Always land back on the SPA; it reads the flag from /me.
    dest = "/#/verified" if row is not None else "/#/verify-failed"
    return RedirectResponse(url=dest, status_code=303)


@router.post("/request-reset")
async def request_reset(payload: ResetRequestPayload):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM users WHERE email = $1;", payload.email.lower())
        if row is not None:
            token = await _issue_email_token(conn, row["id"], "reset", RESET_TTL)
            await send_reset_email(payload.email.lower(), _reset_link(token))
    # Don't reveal whether the email exists.
    return {"status": "ok"}


@router.post("/reset")
async def reset_password(payload: ResetPayload, response: Response):
    th = hash_token(payload.token)
    pw_hash = hash_password(payload.password)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE email_tokens SET used_at = now()
            WHERE token_hash = $1 AND kind = 'reset' AND used_at IS NULL AND expires_at > now()
            RETURNING user_id;
            """,
            th,
        )
        if row is None:
            raise HTTPException(status_code=400, detail="This reset link is invalid or expired.")
        await conn.execute("UPDATE users SET password_hash = $1 WHERE id = $2;", pw_hash, row["user_id"])
        await revoke_user_sessions(conn, row["user_id"])   # force re-login everywhere
    clear_session_cookie(response)
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
        return RedirectResponse(url="/#/login?error=oauth", status_code=303)

    try:
        identity = await oauth.exchange_code(provider, code)
    except Exception as e:
        logger.warning("OAuth exchange failed for %s: %s", provider, e)
        return RedirectResponse(url="/#/login?error=oauth", status_code=303)

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
