import asyncio
import json

import pytest
from starlette.requests import Request
from starlette.responses import StreamingResponse

from novelwiki.modules.experience.adapters.inbound.http import (
    RecapRequest,
    _stream_recap,
    api_recap,
)


class _SlowRecapService:
    def __init__(self):
        self.release = asyncio.Event()
        self.canceled = asyncio.Event()

    async def recap(self, novel_id, ceiling, principal):
        try:
            await self.release.wait()
            return {"answer": f"Through {float(ceiling):g}.", "citations": []}
        except asyncio.CancelledError:
            self.canceled.set()
            raise


@pytest.mark.asyncio
async def test_recap_stream_emits_keepalive_then_result():
    service = _SlowRecapService()
    stream = _stream_recap(
        service, 7, 19, object(), heartbeat_seconds=0
    )

    assert json.loads(await anext(stream)) == {"event": "started"}
    assert json.loads(await anext(stream)) == {"event": "heartbeat"}
    service.release.set()
    await asyncio.sleep(0)
    frame = json.loads(await anext(stream))

    assert frame == {
        "event": "result",
        "data": {"answer": "Through 19.", "citations": []},
    }
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_recap_stream_cancels_work_when_client_disconnects():
    service = _SlowRecapService()
    stream = _stream_recap(service, 7, 19, object())

    assert json.loads(await anext(stream)) == {"event": "started"}
    await asyncio.sleep(0)
    await stream.aclose()

    assert service.canceled.is_set()


@pytest.mark.asyncio
async def test_recap_endpoint_negotiates_streaming_response():
    service = _SlowRecapService()
    service.release.set()
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/novels/7/recap",
        "headers": [(b"accept", b"application/x-ndjson")],
    })

    response = await api_recap(
        7,
        RecapRequest(ceiling=19),
        request,
        user={"id": 1},
        service=service,
        principal_factory=lambda user: object(),
    )
    frames = [json.loads(chunk) async for chunk in response.body_iterator]

    assert isinstance(response, StreamingResponse)
    assert response.media_type == "application/x-ndjson"
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert frames == [
        {"event": "started"},
        {
            "event": "result",
            "data": {"answer": "Through 19.", "citations": []},
        },
    ]
