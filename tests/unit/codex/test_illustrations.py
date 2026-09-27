from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novelwiki.kernel.errors import (
    Conflict,
    Forbidden,
    InvalidOperation,
    NotFound,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
    ValidationFailed,
)
from novelwiki.modules.codex.adapters.inbound import illustrations_http as http
from novelwiki.modules.codex.application.illustrations import complete_scenes
from novelwiki.modules.codex.domain.illustrations import IllustrationPlan, validate_plan


def scene(batch, index, count):
    return {
        "id": f"{batch}-{index}",
        "kind": "scene",
        "style": "luminous",
        "metadata": {"batch": batch, "index": index, "count": count},
    }


def test_gallery_keeps_complete_set_until_replacement_finishes_and_orders_scenes():
    previous = [scene(1, 1, 2), scene(1, 0, 2)]
    incomplete = [scene(2, 1, 3), scene(2, 0, 3)]
    assert [row["id"] for row in complete_scenes(incomplete + previous)] == [
        "1-0",
        "1-1",
    ]
    assert [
        row["id"] for row in complete_scenes([scene(2, 2, 3)] + incomplete + previous)
    ] == [
        "2-0",
        "2-1",
        "2-2",
    ]


def test_scene_evidence_and_total_character_budget_are_enforced():
    quote = "Mira lifted the bronze lantern."
    payload = {
        "characters": [],
        "scenes": [
            {
                "title": "Lantern",
                "caption": "A light in the dark.",
                "evidence": quote,
                "characters": ["mira", "ren", "aya", "oren"],
                "prompt": "A cinematic scene. " * 5,
            },
            {
                "title": "Bridge",
                "caption": "A crossing.",
                "evidence": quote,
                "characters": ["tess"],
                "prompt": "A cinematic scene. " * 5,
            },
        ],
    }
    plan = IllustrationPlan.model_validate(payload)
    with pytest.raises(ValueError, match="at most four"):
        validate_plan(plan, quote, 2, {"mira", "ren", "aya", "oren", "tess"})
    plan.scenes[1].characters = []
    validate_plan(plan, quote, 2, {"mira", "ren", "aya", "oren"})
    with pytest.raises(ValueError, match="exact evidence"):
        validate_plan(
            plan, "This scene is not in the chapter.", 2, {"mira", "ren", "aya", "oren"}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,status",
    [
        (NotFound("missing"), 404),
        (Forbidden("forbidden"), 403),
        (Conflict("changed"), 409),
        (ProviderUnavailable("offline"), 503),
        (QuotaExceeded("queue full"), 429),
        (RateLimited("wait", retry_after=12), 429),
        (ValidationFailed("bad choice"), 422),
        (InvalidOperation("not now"), 400),
    ],
)
async def test_illustration_http_errors_preserve_status_and_retry_after(error, status):
    app = FastAPI()
    app.include_router(http.router, prefix="/api")
    service = SimpleNamespace(generate=AsyncMock(side_effect=error))
    app.dependency_overrides[http.illustration_service_dependency] = lambda: service
    app.dependency_overrides[http.current_user] = lambda: {"id": 1, "role": "user"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/novels/1/chapters/2/illustrations", json={"count": 1}
        )
    assert response.status_code == status
    assert response.json()["detail"] == str(error)
    if isinstance(error, RateLimited):
        assert response.headers["retry-after"] == "12"


def test_character_name_updates_require_known_identity_and_chapter_evidence():
    text = "Mira now called herself Aria, also known as Starling."
    plan = IllustrationPlan.model_validate(
        {
            "characters": [],
            "scenes": [
                {
                    "title": "Meeting",
                    "caption": "A quiet meeting.",
                    "evidence": text,
                    "characters": ["mira"],
                    "prompt": "A luminous scene. " * 5,
                }
            ],
            "name_updates": [
                {
                    "key": "mira",
                    "name": "Aria",
                    "aliases": ["Starling"],
                    "evidence": text,
                }
            ],
        }
    )
    validate_plan(plan, text, 1, {"mira"})
    with pytest.raises(ValueError, match="distinct existing"):
        validate_plan(plan, text, 1, {"someone-else"})
    with pytest.raises(ValueError, match="exact evidence"):
        validate_plan(plan, "An entirely different chapter.", 1, {"mira"})
    plan.name_updates[0].aliases = ["Invented nickname"]
    with pytest.raises(ValueError, match="must appear"):
        validate_plan(plan, text, 1, {"mira"})
    plan.name_updates[0].aliases = []
    plan.name_updates.append(plan.name_updates[0])
    with pytest.raises(ValueError, match="distinct existing"):
        validate_plan(plan, text, 1, {"mira"})


def test_alias_only_update_can_retain_absent_preferred_name_but_not_invent_one():
    text = "Starling answered to her new nickname."
    plan = IllustrationPlan.model_validate(
        {
            "characters": [],
            "scenes": [
                {
                    "title": "Meeting",
                    "caption": "A quiet meeting.",
                    "evidence": text,
                    "characters": ["mira"],
                    "prompt": "A luminous scene. " * 5,
                }
            ],
            "name_updates": [
                {
                    "key": "mira",
                    "name": "Mira",
                    "aliases": ["Starling"],
                    "evidence": text,
                }
            ],
        }
    )
    validate_plan(plan, text, 1, {"mira"}, existing_names={"mira": "Mira"})
    plan.name_updates[0].name = "Invented name"
    with pytest.raises(ValueError, match="must appear"):
        validate_plan(plan, text, 1, {"mira"}, existing_names={"mira": "Mira"})
