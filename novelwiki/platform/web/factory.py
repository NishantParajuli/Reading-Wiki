"""FastAPI infrastructure factory: middleware and security policy only."""
from __future__ import annotations

import hmac
import logging
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from novelwiki.platform.config import settings
from novelwiki.platform.observability.logging import log_event

logger = logging.getLogger(__name__)

_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
    "img-src 'self' data: https:; connect-src 'self'; object-src 'none'; "
    "base-uri 'self'; frame-ancestors 'none'"
)
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
_PUBLIC_AUTH_MUTATIONS = {
    "/api/auth/register", "/api/auth/login", "/api/auth/request-reset",
    "/api/auth/reset", "/api/auth/verify",
}
_REQUEST_HEADER = "x-tideglass-request"
_CSRF_HEADERS = ("x-tideglass-csrf", "x-csrf-token")
_REQUEST_ID_HEADER = "X-Request-ID"
_JOB_LIST_PATH = "/api/jobs"


def _normalized_path(path: str) -> str:
    return path.rstrip("/") or "/"


def _log_completed_request(method: str, path: str, status_code: int) -> bool:
    """Drop successful job-list polling after the route emits state-change records."""
    return not (
        method.upper() == "GET"
        and _normalized_path(path) == _JOB_LIST_PATH
        and status_code < 400
    )


def _csrf_rejection(request):
    if request.method.upper() in _SAFE_METHODS or not request.url.path.startswith("/api"):
        return None
    path = _normalized_path(request.url.path)
    if path in _PUBLIC_AUTH_MUTATIONS:
        if request.headers.get(_REQUEST_HEADER) == "1":
            return None
        return JSONResponse({"detail": "Missing required request header."}, status_code=403)
    cookie = request.cookies.get(settings.CSRF_COOKIE)
    supplied = next((request.headers.get(name) for name in _CSRF_HEADERS
                     if request.headers.get(name)), None)
    if cookie and supplied and hmac.compare_digest(cookie, supplied):
        return None
    return JSONResponse({"detail": "CSRF token missing or invalid."}, status_code=403)


def create_web_app(*, lifespan, seed_csrf_cookie) -> FastAPI:
    app = FastAPI(
        title="Novel Reading Platform",
        description="A multi-novel reading platform with scraping, translation, and a spoiler-safe codex.",
        version="2.0.0",
        lifespan=lifespan,
    )
    origins = [item.strip() for item in settings.ALLOWED_ORIGINS.split(",") if item.strip()]
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        from novelwiki.platform.observability import audit
        incoming = request.headers.get(_REQUEST_ID_HEADER, "").strip()
        request_id = incoming[:64] if incoming else audit.new_request_id()
        token = audit.set_request_id(request_id)
        started = time.monotonic()
        try:
            response = _csrf_rejection(request)
            if response is None:
                response = await call_next(request)
        except Exception:
            if settings.LOG_HTTP_REQUESTS:
                route = request.scope.get("route")
                log_event(
                    logger, logging.ERROR, "http.request.failed",
                    f"{request.method} {request.url.path} failed.",
                    exc_info=True,
                    request_id=request_id,
                    method=request.method,
                    path=request.url.path,
                    route=getattr(route, "path", None),
                    client_ip=request.client.host if request.client else None,
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                )
            raise
        else:
            if settings.LOG_HTTP_REQUESTS:
                route = request.scope.get("route")
                status = int(response.status_code)
                if _log_completed_request(request.method, request.url.path, status):
                    level = logging.WARNING if status >= 400 else logging.INFO
                    content_length = response.headers.get("content-length")
                    log_event(
                        logger, level, "http.request.completed",
                        f"{request.method} {request.url.path} completed with {status}.",
                        request_id=request_id,
                        method=request.method,
                        path=request.url.path,
                        route=getattr(route, "path", None),
                        status_code=status,
                        client_ip=request.client.host if request.client else None,
                        duration_ms=round((time.monotonic() - started) * 1000, 2),
                        response_bytes=(
                            int(content_length)
                            if content_length and content_length.isdigit()
                            else None
                        ),
                    )
        finally:
            audit.reset_request_id(token)
        response.headers[_REQUEST_ID_HEADER] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", _CSP)
        if (request.cookies.get(settings.SESSION_COOKIE)
                and not request.cookies.get(settings.CSRF_COOKIE)):
            seed_csrf_cookie(response)
        return response

    return app
