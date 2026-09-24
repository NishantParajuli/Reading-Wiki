from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novelwiki.kernel.errors import NotFound, ValidationFailed
from novelwiki.modules.identity.public import Principal
from novelwiki.modules.reading.adapters.inbound import http
from novelwiki.modules.reading.application.services import ReadingService


PRINCIPAL = Principal(user_id=7, role="user", email_verified=True, quota_limits={})


@pytest.fixture
def reading():
    repository = AsyncMock()
    repository.chapter_exists.return_value = True
    repository.add_bookmark.return_value = 12
    return ReadingService(repository, AsyncMock()), repository


@pytest.mark.asyncio
async def test_bookmark_rejects_missing_chapter_before_writing(reading):
    service, repository = reading
    repository.chapter_exists.return_value = False

    with pytest.raises(NotFound, match="Chapter not found"):
        await service.add_bookmark(1, PRINCIPAL, 99, "Remember this")

    repository.add_bookmark.assert_not_awaited()


@pytest.mark.asyncio
async def test_bookmark_preserves_existing_fractional_chapters(reading):
    service, repository = reading

    assert await service.add_bookmark(1, PRINCIPAL, 2.5, "Interlude") == 12

    repository.chapter_exists.assert_awaited_once_with(1, 2.5)
    repository.add_bookmark.assert_awaited_once_with(1, 7, 2.5, "Interlude")


@pytest.mark.asyncio
@pytest.mark.parametrize("chapter", [float("nan"), float("inf"), float("-inf")])
async def test_nonfinite_chapters_cannot_be_persisted(reading, chapter):
    service, repository = reading

    with pytest.raises(ValidationFailed):
        await service.add_bookmark(1, PRINCIPAL, chapter, None)
    with pytest.raises(ValidationFailed):
        await service.set_progress(1, PRINCIPAL, chapter, 0)

    repository.add_bookmark.assert_not_awaited()
    repository.set_progress.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("scroll", [float("nan"), float("inf"), float("-inf"), -0.1, 1.1])
async def test_invalid_scroll_positions_cannot_be_persisted(reading, scroll):
    service, repository = reading

    with pytest.raises(ValidationFailed):
        await service.set_progress(1, PRINCIPAL, 2.5, scroll)

    repository.set_progress.assert_not_awaited()


@pytest.fixture
def client(reading):
    service, _repository = reading
    app = FastAPI()
    app.include_router(http.router, prefix="/api")
    app.dependency_overrides[http.current_user] = lambda: {
        "id": 7, "role": "user", "email_verified": True,
    }
    app.dependency_overrides[http.reading_service_dependency] = lambda: service
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("method,path,payload", [
    ("post", "bookmarks", {"chapter": "NaN"}),
    ("post", "bookmarks", {"chapter": "Infinity"}),
    ("put", "progress", {"last_chapter": "NaN"}),
    ("put", "progress", {"last_chapter": 1, "scroll_pct": "NaN"}),
    ("put", "progress", {"last_chapter": 1, "scroll_pct": "Infinity"}),
    ("put", "progress", {"last_chapter": 1, "scroll_pct": -0.1}),
    ("put", "progress", {"last_chapter": 1, "scroll_pct": 1.1}),
])
def test_invalid_reading_requests_return_422(client, reading, method, path, payload):
    response = getattr(client, method)(f"/api/novels/1/{path}", json=payload)

    assert response.status_code == 422
    reading[1].add_bookmark.assert_not_awaited()
    reading[1].set_progress.assert_not_awaited()


def test_missing_bookmark_chapter_returns_404(client, reading):
    reading[1].chapter_exists.return_value = False

    response = client.post("/api/novels/1/bookmarks", json={"chapter": 99})

    assert response.status_code == 404
    reading[1].add_bookmark.assert_not_awaited()


@pytest.mark.parametrize("scroll", [0, 0.5, 1])
def test_valid_progress_remains_supported(client, reading, scroll):
    response = client.put(
        "/api/novels/1/progress", json={"last_chapter": 2.5, "scroll_pct": scroll},
    )

    assert response.status_code == 200
    reading[1].set_progress.assert_awaited_once_with(1, 7, 2.5, scroll)
