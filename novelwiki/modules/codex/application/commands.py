"""Application commands shared by Codex transports."""
from __future__ import annotations


class CodexCommands:
    def __init__(self, *, chunk, embed, extract, rebuild, merge):
        self._chunk = chunk
        self._embed = embed
        self._extract = extract
        self._rebuild = rebuild
        self._merge = merge

    async def chunk(self, novel_id, force=False, start=None, end=None):
        return await self._chunk(novel_id, force=force, from_chapter=start, to_chapter=end)

    async def embed(self, novel_id, start=None, end=None):
        return await self._embed(novel_id, from_chapter=start, to_chapter=end)

    async def extract(self, novel_id, force=False, start=None, end=None):
        return await self._extract(novel_id, force=force, from_chapter=start, to_chapter=end)

    async def rebuild(self, novel_id):
        return await self._rebuild(novel_id)

    async def merge(self, novel_id, keep_id, drop_id):
        return await self._merge(novel_id, keep_id, drop_id)
