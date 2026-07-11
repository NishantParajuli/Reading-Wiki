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

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator

from novelwiki.platform.config import settings
from novelwiki.modules.identity.adapters.outbound import oauth, rate_limit
from novelwiki.modules.identity.adapters.inbound.dependencies import current_user
from novelwiki.modules.identity.adapters.outbound.email import send_verification_email, send_reset_email
from novelwiki.modules.identity.adapters.outbound.passwords import hash_password, verify_password
from novelwiki.modules.identity.adapters.inbound.cookies import (
    clear_session_cookie, set_session_cookie,
)
from novelwiki.modules.identity.adapters.outbound.tokens import new_token, hash_token, sign, unsign, stamped
from novelwiki.modules.identity.adapters.inbound.presentation import self_user_with_capabilities
from novelwiki.modules.identity.domain.policies import normalize_username, valid_username
from novelwiki.modules.identity.application.ports import AuthPersistence, DuplicateRegistration

logger = logging.getLogger(__name__)
router = APIRouter()


async def identity_auth_persistence_dependency() -> AuthPersistence:
    raise RuntimeError("Identity auth persistence is not configured")

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


async def _ensure_or_429(
    persistence: AuthPersistence, key: str, limit: rate_limit.RateLimit,
    request: Request, scope: str,
) -> None:
    try:
        await persistence.ensure_rate(key, limit)
    except rate_limit.RateLimitExceeded as exc:
        _log_auth_event("throttle", request, scope)
        _rate_limited(exc)


async def _consume_or_429(
    persistence: AuthPersistence, key: str, limit: rate_limit.RateLimit,
    request: Request, scope: str,
) -> None:
    try:
        await persistence.consume_rate(key, limit)
    except rate_limit.RateLimitExceeded as exc:
        _log_auth_event("throttle", request, scope)
        _rate_limited(exc)


async def _consume_silent(
    persistence: AuthPersistence, key: str, limit: rate_limit.RateLimit,
    request: Request, scope: str,
) -> bool:
    try:
        await persistence.consume_rate(key, limit)
        return True
    except rate_limit.RateLimitExceeded:
        _log_auth_event("throttle", request, scope)
        return False


# ── email + password ──────────────────────────────────────────────────────

@router.post("/register")
async def register(
    payload: RegisterPayload, request: Request, response: Response,
    persistence: AuthPersistence = Depends(identity_auth_persistence_dependency),
):
    email = payload.email.lower()
    username = normalize_username(payload.username)
    if not valid_username(username):
        raise HTTPException(status_code=422, detail="Username must be 3–24 chars: a–z, 0–9, underscore.")
    ip_key = rate_limit.bucket_key("auth:register:ip", rate_limit.client_ip(request))
    await _consume_or_429(persistence, ip_key, _register_ip_limit(), request, "register:ip")
    token = new_token()
    try:
        row, session = await persistence.register_user(
            email, username, hash_password(payload.password), token,
            dt.datetime.now(dt.timezone.utc) + VERIFY_TTL,
            request.headers.get("user-agent"),
        )
    except DuplicateRegistration as exc:
        raise HTTPException(status_code=409, detail=f"That {exc.field} is already taken.")
    await send_verification_email(email, _verify_link(token))
    set_session_cookie(response, session)
    return await self_user_with_capabilities(dict(row))


@router.post("/login")
async def login(
    payload: LoginPayload, request: Request, response: Response,
    persistence: AuthPersistence = Depends(identity_auth_persistence_dependency),
):
    ident = payload.identifier.strip()
    ident_key = ident.lower()
    ip_key = rate_limit.bucket_key("auth:login:ip", rate_limit.client_ip(request))
    account_key = rate_limit.bucket_key("auth:login:account", ident_key)
    await _ensure_or_429(persistence, ip_key, _login_ip_limit(), request, "login:ip")
    await _ensure_or_429(persistence, account_key, _login_account_limit(), request, "login:account")
    row = await persistence.find_login_user(ident_key)
    if row is None or not row["password_hash"] or not verify_password(row["password_hash"], payload.password):
        await _consume_or_429(persistence, ip_key, _login_ip_limit(), request, "login:ip")
        await _consume_or_429(persistence, account_key, _login_account_limit(), request, "login:account")
        _log_auth_event("failure", request, "login")
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    if row["status"] != "active":
        _log_auth_event("failure", request, "login:status")
        raise HTTPException(status_code=403, detail="This account is suspended.")
    await persistence.clear_rate(ip_key)
    await persistence.clear_rate(account_key)
    session = await persistence.create_user_session(row["id"], request.headers.get("user-agent"))
    set_session_cookie(response, session)
    return await self_user_with_capabilities(dict(row))


@router.post("/logout")
async def logout(
    request: Request, response: Response,
    persistence: AuthPersistence = Depends(identity_auth_persistence_dependency),
):
    token = request.cookies.get(settings.SESSION_COOKIE)
    if token:
        await persistence.revoke_session(token)
    clear_session_cookie(response)
    return {"status": "ok"}


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    return await self_user_with_capabilities(user)


@router.get("/links")
async def oauth_links(
    user: dict = Depends(current_user),
    persistence: AuthPersistence = Depends(identity_auth_persistence_dependency),
):
    """Which OAuth providers are linked to the signed-in account (account panel)."""
    linked = await persistence.linked_providers(user["id"])
    return {"linked": linked, "has_password": bool(user.get("password_hash"))}


@router.post("/change-password")
async def change_password(payload: ChangePasswordPayload, request: Request, response: Response,
                          user: dict = Depends(current_user),
                          persistence: AuthPersistence = Depends(identity_auth_persistence_dependency)):
    """Set or change the account password. If one is already set, the current one must match.
    Succeeds for OAuth-only users (no current password) so they can add password login.
    All other sessions are revoked; this device gets a fresh session so it stays signed in."""
    if user.get("password_hash"):
        if not payload.current_password or not verify_password(user["password_hash"], payload.current_password):
            raise HTTPException(status_code=403, detail="Current password is incorrect.")
    new_hash = hash_password(payload.new_password)
    session = await persistence.change_password(
        user["id"], new_hash, request.headers.get("user-agent"),
    )
    set_session_cookie(response, session)
    return {"status": "ok"}


@router.get("/verify")
async def verify_email(
    token: str,
    persistence: AuthPersistence = Depends(identity_auth_persistence_dependency),
):
    th = hash_token(token)
    valid = await persistence.verification_token_valid(th)
    dest = f"/verify?token={token}" if valid else "/verify-failed"
    return RedirectResponse(url=dest, status_code=303)


@router.post("/request-reset")
async def request_reset(
    payload: ResetRequestPayload, request: Request,
    persistence: AuthPersistence = Depends(identity_auth_persistence_dependency),
):
    email = payload.email.lower()
    should_issue = True
    ip_key = rate_limit.bucket_key("auth:reset-request:ip", rate_limit.client_ip(request))
    email_key = rate_limit.bucket_key("auth:reset-request:email", email)
    should_issue = await _consume_silent(
        persistence, ip_key, _reset_request_ip_limit(), request, "reset-request:ip",
    )
    should_issue = (
        await _consume_silent(
            persistence, email_key, _reset_request_email_limit(), request, "reset-request:email",
        )
    ) and should_issue
    token = new_token() if should_issue else None
    if token is not None:
        issued = await persistence.issue_reset_token(
            email, token, dt.datetime.now(dt.timezone.utc) + RESET_TTL,
        )
        if not issued:
            token = None
    if token is not None:
        await send_reset_email(email, _reset_link(token))
    # Don't reveal whether the email exists.
    return {"status": "ok"}


@router.post("/reset")
async def reset_password(
    payload: ResetPayload, request: Request, response: Response,
    persistence: AuthPersistence = Depends(identity_auth_persistence_dependency),
):
    th = hash_token(payload.token)
    ip_key = rate_limit.bucket_key("auth:reset-submit:ip", rate_limit.client_ip(request))
    token_key = rate_limit.bucket_key("auth:reset-submit:token", th)
    await _consume_or_429(persistence, ip_key, _reset_submit_ip_limit(), request, "reset-submit:ip")
    await _consume_or_429(persistence, token_key, _reset_submit_token_limit(), request, "reset-submit:token")
    if not await persistence.reset_password(th, hash_password(payload.password)):
        _log_auth_event("failure", request, "reset-submit")
        raise HTTPException(status_code=400, detail="This reset link is invalid or expired.")
    clear_session_cookie(response)
    return {"status": "ok"}


@router.post("/verify")
async def verify_email_confirm(
    payload: VerifyPayload,
    persistence: AuthPersistence = Depends(identity_auth_persistence_dependency),
):
    th = hash_token(payload.token)
    if not await persistence.confirm_verification(th):
        raise HTTPException(status_code=400, detail="This verification link is invalid or expired.")
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
async def oauth_callback(
    provider: str, request: Request, code: str | None = None,
    state: str | None = None,
    persistence: AuthPersistence = Depends(identity_auth_persistence_dependency),
):
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

    user, session = await persistence.oauth_login(
        provider, identity, request.headers.get("user-agent"),
    )

    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    set_session_cookie(resp, session)
    return resp
