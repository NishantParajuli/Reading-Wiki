from __future__ import annotations

from typing import Protocol

from novelwiki.modules.identity.public import Principal


class NovelLike(Protocol):
    owner_id: int | None
    visibility: str


def can_read(novel: NovelLike, principal: Principal | None) -> bool:
    if novel.visibility in ("global", "public"):
        return True
    return principal is not None and (
        novel.owner_id == principal.user_id or principal.is_admin
    )


def can_edit(novel: NovelLike, principal: Principal | None) -> bool:
    return principal is not None and (
        novel.owner_id == principal.user_id or principal.is_admin
    )
