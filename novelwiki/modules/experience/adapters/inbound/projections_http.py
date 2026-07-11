from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from novelwiki.auth.deps import current_user
from novelwiki.kernel.errors import Forbidden, NotFound
from novelwiki.modules.identity.public import Principal

from ...application import ExperienceProjectionService

router = APIRouter()


async def experience_projection_service_dependency() -> ExperienceProjectionService:
    raise RuntimeError("ExperienceProjectionService was not wired by the composition root")


def _raise_http(exc: Exception) -> None:
    status = 404 if isinstance(exc, NotFound) else 403
    raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/novels")
async def api_list_novels(
    user: dict = Depends(current_user),
    service: ExperienceProjectionService = Depends(experience_projection_service_dependency),
):
    """The caller's library grid: only novels they own or have explicitly added to their
    library. Shared (global/public) novels are *not* in the library until added from Discover.
    Shelf is per-user; status tags are the novel's own (owner/admin-curated) metadata."""
    return await service.library_cards(Principal.from_user(user))


@router.get("/novels/{novel_id}")
async def api_get_novel(
    novel_id: int,
    user: dict = Depends(current_user),
    service: ExperienceProjectionService = Depends(experience_projection_service_dependency),
):
    try:
        return await service.novel_detail(novel_id, Principal.from_user(user))
    except (NotFound, Forbidden) as exc:
        _raise_http(exc)


@router.get("/discover")
async def api_discover(
    user: dict = Depends(current_user), q: str | None = None,
    language: str | None = None, tag: str | None = None,
    translation: str | None = None, has_codex: bool | None = None,
    has_audio: bool | None = None, freshness: str | None = None,
    sort: str = "recent", offset: int = 0, limit: int = 60,
    service: ExperienceProjectionService = Depends(experience_projection_service_dependency),
):
    """Browse the shared library — Global + Public novels the caller hasn't added yet — with
    optional filters. `translation` is the derived translation_type (translated|raws|raws+translated);
    `tag` matches any of a novel's owner-curated status tags, and `freshness` is fresh_7d |
    fresh_30d | stale_30d | never_scraped. `sort` is recent | fresh | title. Paginated via
    offset/limit (max 100); returns ``{items, total, offset, limit}``."""
    return await service.discover(
        Principal.from_user(user), q=q, language=language, tag=tag,
        translation=translation, has_codex=has_codex, has_audio=has_audio,
        freshness=freshness, sort=sort, offset=offset, limit=limit,
    )


@router.get("/users/{username}")
async def api_user_profile(
    username: str,
    user: dict = Depends(current_user),
    service: ExperienceProjectionService = Depends(experience_projection_service_dependency),
):
    """A public profile: identity, reading stats, and recent activity. When viewing your
    own profile (or as an admin) private novels are included; otherwise activity is limited
    to the shared library (global/public) so a reader's private list isn't leaked."""
    try:
        return await service.public_profile(username, Principal.from_user(user))
    except NotFound as exc:
        _raise_http(exc)
