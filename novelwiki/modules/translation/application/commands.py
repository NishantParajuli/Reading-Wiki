"""Application command for a glossary-aware translation range."""
from __future__ import annotations


class TranslationCommands:
    def __init__(self, translate_range, seed_glossary):
        self._translate_range = translate_range
        self._seed_glossary = seed_glossary

    async def translate(self, novel_id, start=None, end=None, force=False, seed=False):
        seeded = await self._seed_glossary(novel_id) if seed else None
        translated = await self._translate_range(
            novel_id, from_chapter=start, to_chapter=end, force=force
        )
        return seeded, translated
