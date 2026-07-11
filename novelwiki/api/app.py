"""Stable ASGI entrypoint.

The application factory, middleware, lifecycle, and static hosting are owned by Platform Web.
"""

from novelwiki.platform.web.app import app

__all__ = ["app"]
