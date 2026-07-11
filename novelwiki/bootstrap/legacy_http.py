"""Explicit ownership registry for handlers awaiting application-layer extraction.

The registered APIRoute objects retain their exact endpoint signatures and OpenAPI contracts,
but the aggregate legacy router is never mounted. Every bridge has one canonical module owner.
"""

from __future__ import annotations

from fastapi import APIRouter

from novelwiki.legacy.routes import router as legacy_router

OWNERS: dict[str, frozenset[str]] = {
    "identity": frozenset(),
    "catalog": frozenset(),
    "reading": frozenset(),
    "acquisition": frozenset(),
    "translation": frozenset(),
    "codex": frozenset(),
    "experience": frozenset(),
}

_route_by_name = {route.endpoint.__name__: route for route in legacy_router.routes}
_assigned = set().union(*OWNERS.values())
_available = set(_route_by_name)
if _assigned != _available:
    missing = sorted(_available - _assigned)
    unknown = sorted(_assigned - _available)
    raise RuntimeError(
        f"Legacy HTTP ownership registry drifted; missing={missing}, unknown={unknown}"
    )


def router_for(owner: str) -> APIRouter:
    names = OWNERS[owner]
    router = APIRouter()
    router.routes.extend(
        route for route in legacy_router.routes if route.endpoint.__name__ in names
    )
    return router
