import httpx
import pytest

from tools.benchmark_queries import _validate_endpoint_response


@pytest.mark.parametrize("status", [302, 401, 403, 404, 500])
def test_endpoint_benchmark_rejects_every_non_success_status(status):
    with pytest.raises(RuntimeError, match=f"expected 200, returned {status}"):
        _validate_endpoint_response(httpx.Response(status, json={}), "discover", 7, "Fixture")


@pytest.mark.parametrize("payload", [
    {}, [], {"detail": "Not authenticated"},
    {"items": [], "total": 0, "offset": 0, "limit": 1},
    {"items": [{"id": 8, "title": "Wrong book", "chapter_count": 1}], "total": 1, "offset": 0, "limit": 1},
])
def test_endpoint_benchmark_requires_its_populated_discover_fixture(payload):
    with pytest.raises(RuntimeError, match="unexpected response data"):
        _validate_endpoint_response(httpx.Response(200, json=payload), "discover", 7, "Fixture")


def test_endpoint_benchmark_rejects_non_json_success():
    with pytest.raises(RuntimeError, match="invalid JSON"):
        _validate_endpoint_response(httpx.Response(200, text="OK"), "discover", 7, "Fixture")
