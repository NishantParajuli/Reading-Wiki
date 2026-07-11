"""Health and static-file infrastructure mounted after all API routes."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from novelwiki.platform.config import settings

logger = logging.getLogger(__name__)


class SpaStaticFiles(StaticFiles):
    def file_response(self, full_path, *args, **kwargs):
        response = super().file_response(full_path, *args, **kwargs)
        if "/assets/" in str(full_path).replace("\\", "/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response

    async def get_response(self, path: str, scope):
        from starlette.exceptions import HTTPException as StarletteHTTPException
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            last = path.rsplit("/", 1)[-1]
            if exc.status_code == 404 and "." not in last:
                return await super().get_response("index.html", scope)
            raise


def mount_platform_surfaces(app, *, ensure_owner_assets) -> None:
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "service": "novelwiki-backend"}

    try:
        ensure_owner_assets()
        avatar_dir = Path(settings.ASSET_DIR) / "_users"
        avatar_dir.mkdir(parents=True, exist_ok=True)
        app.mount("/assets/_users", StaticFiles(directory=str(avatar_dir)), name="user-assets")
    except Exception as exc:
        logger.warning("Could not mount public avatar assets folder: %s", exc)
    try:
        app.mount("/", SpaStaticFiles(directory="novelwiki/frontend/dist", html=True), name="frontend")
    except Exception as exc:
        logger.warning(
            "Could not mount static frontend folder (run `npm run build` in novelwiki/frontend): %s",
            exc,
        )
