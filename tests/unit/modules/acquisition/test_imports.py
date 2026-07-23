from __future__ import annotations

import pytest

from novelwiki.modules.acquisition.adapters.outbound.importer.commit import (
    _apply_metadata_override,
)
from novelwiki.modules.acquisition.application.imports import (
    ImportConfig,
    ImportRequestError,
    ImportService,
)
from novelwiki.modules.acquisition.domain.document import Document
from novelwiki.modules.identity.public import Principal


class _Gateway:
    def __init__(self):
        self.job = {
            "id": 31,
            "user_id": 7,
            "status": "awaiting_review",
            "options": {"is_raw": False},
            "detected_meta": {
                "title": "Vol 2",
                "language": "en",
                "cover_sha": "a" * 64,
            },
        }
        self.updated = None

    async def get_job(self, job_id):
        return self.job if job_id == 31 else None

    def block_count(self, job_id):
        return 4

    async def update_job(self, job_id, **fields):
        self.updated = (job_id, fields)


class _Catalog:
    pass


class _Spend:
    pass


def _service(gateway):
    return ImportService(
        gateway,
        _Catalog(),
        _Spend(),
        ImportConfig(
            incoming_dir="/tmp/imports",
            max_upload_bytes=100,
            max_upload_mb=1,
            max_chunked_bytes=100,
            max_chunked_upload_mb=1,
        ),
    )


PRINCIPAL = Principal(user_id=7, role="user")
PLAN = {
    "segments": [{
        "id": "chapter-1",
        "title": "Chapter 1",
        "kind": "chapter",
        "number": 1,
        "include": True,
        "block_range": [0, 3],
    }],
}


@pytest.mark.asyncio
async def test_review_metadata_is_saved_as_authoritative_override():
    gateway = _Gateway()

    await _service(gateway).update_plan(
        31,
        PLAN,
        PRINCIPAL,
        metadata={
            "title": "Mushoku Tensei Vol. 2",
            "author": "Rifujin na Magonote",
            "series": "Mushoku Tensei",
            "series_index": 2,
            "volume_label": "Volume II",
        },
    )

    job_id, fields = gateway.updated
    override = fields["options"]["metadata_override"]
    assert job_id == 31
    assert override == {
        "title": "Mushoku Tensei Vol. 2",
        "author": "Rifujin na Magonote",
        "series": "Mushoku Tensei",
        "series_index": 2.0,
        "volume_label": "Volume II",
    }
    assert fields["detected_meta"]["cover_sha"] == "a" * 64
    assert fields["detected_meta"]["series"] == "Mushoku Tensei"


@pytest.mark.asyncio
async def test_review_rejects_non_finite_volume_number():
    gateway = _Gateway()
    with pytest.raises(ImportRequestError, match="finite"):
        await _service(gateway).update_plan(
            31, PLAN, PRINCIPAL, metadata={"series_index": float("nan")}
        )


def test_commit_applies_only_editable_metadata_overrides():
    document = Document(
        blocks=[],
        meta={
            "title": "Vol 2",
            "series": None,
            "cover_sha": "b" * 64,
            "assets": {"original": {}},
        },
        format="pdf",
    )

    _apply_metadata_override(document, {
        "metadata_override": {
            "title": "Mushoku Tensei Vol. 2",
            "series": "Mushoku Tensei",
            "series_index": 2.0,
            "volume_label": "Volume II",
            "cover_sha": "attacker-controlled",
            "assets": {},
        },
    })

    assert document.meta["title"] == "Mushoku Tensei Vol. 2"
    assert document.meta["series"] == "Mushoku Tensei"
    assert document.meta["series_index"] == 2.0
    assert document.meta["volume_label"] == "Volume II"
    assert document.meta["cover_sha"] == "b" * 64
    assert document.meta["assets"] == {"original": {}}
