from __future__ import annotations

import pytest

from novelwiki.modules.acquisition.adapters.outbound.importer.segment import (
    _classify,
    _refine_batch,
)


def test_unnumbered_epilogue_is_included_narrative():
    assert _classify("Epilogue", None) == ("interlude", True)
    assert _classify("Epilogue: The Journey Home", None) == ("interlude", True)


class _BadRefiner:
    async def call_llm(self, *args, **kwargs):
        return (
            '{"segments":[{"id":"s1","kind":"backmatter",'
            '"title":"Epilogue","number":null,"part_label":null,'
            '"include":false}]}'
        )


@pytest.mark.asyncio
async def test_refiner_cannot_demote_explicit_epilogue():
    segment = {
        "id": "s1",
        "title": "Epilogue",
        "kind": "interlude",
        "number": 28.5,
        "word_count": 2200,
        "first_line": "They returned home.",
        "include": True,
    }

    await _refine_batch([segment], {"s1": segment}, "A Novel", runtime=_BadRefiner())

    assert segment["kind"] == "interlude"
    assert segment["include"] is True
    assert segment["number"] == 28.5
