"""Production bootstrap must register protected API routes before the SPA mount."""

from starlette.routing import Match
from novelwiki.api.app import app


def test_illustration_routes_win_over_frontend_fallback():
    for method, path in [
        ("GET", "/api/novels/1/chapters/1/illustrations"),
        ("POST", "/api/novels/1/chapters/1/illustrations"),
        (
            "GET",
            "/api/novels/1/illustrations/4d8f5e96-fbfe-429a-9ba5-5f58cbfd9e21/image",
        ),
    ]:
        scope = {"type": "http", "path": path, "method": method, "root_path": ""}
        first = next(
            route for route in app.routes if route.matches(scope)[0] is Match.FULL
        )
        assert first.name in {
            "illustrations",
            "generate_illustrations",
            "illustration_image",
        }
