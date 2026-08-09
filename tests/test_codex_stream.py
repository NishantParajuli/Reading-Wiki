import asyncio
import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import StreamingResponse

from novelwiki.modules.codex.adapters.inbound.http import (
    AskRequest,
    _stream_codex_result,
    api_get_entity_profile,
    ask_question,
)


class _SlowQueries:
    def __init__(self):
        self.release = asyncio.Event()
        self.canceled = asyncio.Event()

    async def ask(self, novel_id, question, ceiling, principal):
        try:
            await self.release.wait()
            return {"answer": question, "citations": []}
        except asyncio.CancelledError:
            self.canceled.set()
            raise

    async def entity_profile(self, novel_id, entity_id, ceiling, principal):
        await self.release.wait()
        return {"id": entity_id, "canonical_name": "Hero"}


def _request(method: str, accept: str = "application/x-ndjson") -> Request:
    return Request({
        "type": "http",
        "method": method,
        "path": "/api/test",
        "headers": [(b"accept", accept.encode())],
    })


@pytest.mark.asyncio
async def test_codex_stream_emits_keepalive_then_result():
    queries = _SlowQueries()
    stream = _stream_codex_result(
        lambda: queries.ask(7, "Who?", 19, object()),
        failure_detail="failed",
        heartbeat_seconds=0,
    )

    assert json.loads(await anext(stream)) == {"event": "started"}
    assert json.loads(await anext(stream)) == {"event": "heartbeat"}
    queries.release.set()
    await asyncio.sleep(0)
    assert json.loads(await anext(stream)) == {
        "event": "result",
        "data": {"answer": "Who?", "citations": []},
    }


@pytest.mark.asyncio
async def test_codex_stream_cancels_work_when_client_disconnects():
    queries = _SlowQueries()
    stream = _stream_codex_result(
        lambda: queries.ask(7, "Who?", 19, object()),
        failure_detail="failed",
    )

    assert json.loads(await anext(stream)) == {"event": "started"}
    await asyncio.sleep(0)
    await stream.aclose()

    assert queries.canceled.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["ask", "entity"])
async def test_codex_endpoint_negotiates_streaming_response(surface):
    queries = _SlowQueries()
    queries.release.set()
    service = SimpleNamespace(queries=queries)

    if surface == "ask":
        response = await ask_question(
            7,
            AskRequest(question="Who?", ceiling=19),
            _request("POST"),
            user={"id": 1},
            service=service,
            principal_factory=lambda user: object(),
        )
    else:
        response = await api_get_entity_profile(
            7,
            42,
            19,
            _request("GET"),
            user={"id": 1},
            service=service,
            principal_factory=lambda user: object(),
        )

    frames = [json.loads(chunk) async for chunk in response.body_iterator]
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "application/x-ndjson"
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert frames[0] == {"event": "started"}
    assert frames[-1]["event"] == "result"


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["ask", "entity"])
async def test_codex_endpoint_preserves_plain_json_response(surface):
    queries = _SlowQueries()
    queries.release.set()
    service = SimpleNamespace(queries=queries)

    if surface == "ask":
        response = await ask_question(
            7,
            AskRequest(question="Who?", ceiling=19),
            _request("POST", "application/json"),
            user={"id": 1},
            service=service,
            principal_factory=lambda user: object(),
        )
        assert response == {"answer": "Who?", "citations": []}
    else:
        response = await api_get_entity_profile(
            7,
            42,
            19,
            _request("GET", "application/json"),
            user={"id": 1},
            service=service,
            principal_factory=lambda user: object(),
        )
        assert response == {"id": 42, "canonical_name": "Hero"}
