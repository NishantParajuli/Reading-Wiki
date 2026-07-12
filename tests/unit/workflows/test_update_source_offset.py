from __future__ import annotations

from types import SimpleNamespace

import pytest

from novelwiki.modules.acquisition.public import AcquisitionTransactionApi
from novelwiki.modules.codex.public import CodexTransactionApi
from novelwiki.modules.reading.public import ReadingTransactionApi
from novelwiki.workflows.update_source_offset import update_source_offset


class _Transaction:
    def __init__(self, bindings):
        self._bindings = bindings

    def bind(self, capability):
        return self._bindings[capability]


class _Uow:
    def __init__(self, bindings):
        self.transaction = _Transaction(bindings)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


@pytest.mark.asyncio
async def test_update_source_offset_blocks_any_codex_chapter_artifact():
    events = []

    class Acquisition:
        async def source_offset_state(self, source_id):
            return 9, 1.0

        async def set_source_offset(self, source_id, offset):
            events.append(("offset", source_id, offset))

    class Reading:
        async def source_chapter_numbers(self, source_id):
            return (1.0, 2.0)

        async def renumber_source_chapters(self, *args):
            events.append(("renumber", *args))
            return 2

    class Codex:
        async def has_chapter_artifacts(self, novel_id, chapters):
            events.append(("guard", novel_id, chapters))
            return True

    bindings = {
        AcquisitionTransactionApi: Acquisition(),
        ReadingTransactionApi: Reading(),
        CodexTransactionApi: Codex(),
    }
    with pytest.raises(ValueError, match="codex artifacts"):
        await update_source_offset(lambda: _Uow(bindings), 4, 3.0)
    assert events == [("guard", 9, (1.0, 2.0))]


@pytest.mark.asyncio
async def test_update_source_offset_renumbers_then_updates_offset_when_clear():
    events = []
    acquisition = SimpleNamespace()

    async def source_offset_state(_source_id):
        return 9, 1.0

    async def set_source_offset(source_id, offset):
        events.append(("offset", source_id, offset))

    acquisition.source_offset_state = source_offset_state
    acquisition.set_source_offset = set_source_offset

    class Reading:
        async def source_chapter_numbers(self, source_id):
            return (1.0, 2.0)

        async def renumber_source_chapters(self, source_id, novel_id, delta):
            events.append(("renumber", source_id, novel_id, delta))
            return 2

    class Codex:
        async def has_chapter_artifacts(self, novel_id, chapters):
            return False

    bindings = {
        AcquisitionTransactionApi: acquisition,
        ReadingTransactionApi: Reading(),
        CodexTransactionApi: Codex(),
    }
    assert await update_source_offset(lambda: _Uow(bindings), 4, 3.0) == 2
    assert events == [("renumber", 4, 9, 2.0), ("offset", 4, 3.0)]
