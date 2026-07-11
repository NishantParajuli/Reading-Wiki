"""Hand-rolled OAuth2 authorization-code flow for Google + Discord (httpx only).

State/CSRF is carried in a short-lived signed cookie (see router), not server session
state, so this stays stateless and works behind the Cloudflare tunnel.
"""
from urllib.parse import urlencode

import httpx

from novelwiki.platform.config import settings

PROVIDERS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "userinfo": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
    },
    "discord": {
        "authorize": "https://discord.com/oauth2/authorize",
        "token": "https://discord.com/api/oauth2/token",
        "userinfo": "https://discord.com/api/users/@me",
        "scope": "identify email",
    },
}


def _creds(provider: str) -> tuple[str, str]:
    if provider == "google":
        return settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
    if provider == "discord":
        return settings.DISCORD_CLIENT_ID, settings.DISCORD_CLIENT_SECRET
    return "", ""


def is_configured(provider: str) -> bool:
    cid, secret = _creds(provider)
    return provider in PROVIDERS and bool(cid and secret)


def configured_providers() -> list[str]:
    return [p for p in PROVIDERS if is_configured(p)]


def redirect_uri(provider: str) -> str:
    return f"{settings.PUBLIC_BASE_URL}/api/auth/oauth/{provider}/callback"


def authorize_url(provider: str, state: str) -> str:
    cid, _ = _creds(provider)
    cfg = PROVIDERS[provider]
    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri(provider),
        "response_type": "code",
        "scope": cfg["scope"],
        "state": state,
    }
    if provider == "google":
        params["access_type"] = "online"
        params["prompt"] = "select_account"
    return f"{cfg['authorize']}?{urlencode(params)}"


async def exchange_code(provider: str, code: str) -> dict:
    """Exchange the auth code for a normalized identity:
    {provider_account_id, email, name, email_verified}."""
    cid, secret = _creds(provider)
    cfg = PROVIDERS[provider]
    data = {
        "client_id": cid,
        "client_secret": secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(provider),
    }
    async with httpx.AsyncClient(timeout=15) as client:
        tok_resp = await client.post(cfg["token"], data=data, headers={"Accept": "application/json"})
        tok_resp.raise_for_status()
        access = tok_resp.json().get("access_token")
        if not access:
            raise ValueError("OAuth token exchange returned no access_token")
        ui_resp = await client.get(cfg["userinfo"], headers={"Authorization": f"Bearer {access}"})
        ui_resp.raise_for_status()
        ui = ui_resp.json()

    if provider == "google":
        return {
            "provider_account_id": str(ui["sub"]),
            "email": (ui.get("email") or "").lower() or None,
            "name": ui.get("name"),
            "email_verified": bool(ui.get("email_verified")),
        }
    # discord
    return {
        "provider_account_id": str(ui["id"]),
        "email": (ui.get("email") or "").lower() or None,
        "name": ui.get("global_name") or ui.get("username"),
        "email_verified": bool(ui.get("verified")),
    }
