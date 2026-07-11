"""Stable compatibility helper for resolving narration chapter text."""


async def resolve_chapter_text(novel_id: int, number: float, user: dict | None) -> dict:
    from novelwiki.bootstrap.reading_migration import build_reading_narration_gateway

    gateway = await build_reading_narration_gateway()
    return await gateway.resolve_narration_text(
        novel_id, number, int(user["id"]) if isinstance(user, dict) else None
    )
