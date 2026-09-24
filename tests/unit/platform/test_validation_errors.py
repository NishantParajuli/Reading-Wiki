from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
import pytest

from novelwiki.platform.web.factory import create_web_app


class FiniteRequest(BaseModel):
    chapter: float = Field(allow_inf_nan=False)
    progress: float = Field(ge=0, le=1, allow_inf_nan=False)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity"])
def test_nonstandard_numeric_json_returns_validation_error_instead_of_500(number):
    app = create_web_app(lifespan=None, seed_csrf_cookie=lambda response: None)

    @app.post("/validation-test")
    def validate(body: FiniteRequest):
        pytest.fail("Invalid input reached the application")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/validation-test", content=f'{{"chapter":{number},"progress":{number}}}',
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 422
    assert len(response.json()["detail"]) == 2
    assert response.headers["X-Content-Type-Options"] == "nosniff"
