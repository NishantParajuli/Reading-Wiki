from __future__ import annotations

from pathlib import Path

import pytest

from novelwiki.kernel.errors import NotFound
from novelwiki.modules.acquisition.adapters.outbound.assets import (
    AcquisitionAssetFilesystem,
)
from novelwiki.modules.acquisition.application.ports import AssetFile, ImportAssetOwner
from novelwiki.modules.acquisition.application.sources import (
    AcquisitionService,
    ScheduleScrape,
)
from novelwiki.modules.identity.public import Principal


class _Catalog:
    async def require_readable(self, novel_id, principal):
        return None

    async def require_editable(self, novel_id, principal):
        return None


class _Urls:
    async def validate(self, url):
        return url


class _Spend:
    def ensure_allowed(self, principal):
        return None


class _Work:
    def __init__(self, created=True):
        self.created = created
        self.call = None

    async def schedule(self, **kwargs):
        self.call = kwargs
        return 73, self.created


class _Filesystem:
    def normalize_filename(self, filename):
        return "a" * 64, "png", f"{'a' * 64}.png"

    def novel_relative_path(self, novel_id, sha256, extension):
        return f"{novel_id}/{sha256}.{extension}"

    def novel_file(self, novel_id, safe_name, mime):
        return AssetFile(Path("/tmp/asset.png"), mime or "image/png")

    def staged_file(self, job_id, safe_name):
        return AssetFile(Path("/tmp/staged.png"), "image/png")


class _Repository:
    def __init__(self):
        self.exists = True
        self.updated = None
        self.owner = ImportAssetOwner(7, {})

    async def create_source(self, novel_id, draft):
        return 4

    async def source_exists(self, novel_id, source_id):
        return self.exists

    async def update_source(self, source_id, fields):
        self.updated = (source_id, fields)
        return 3

    async def novel_asset(self, novel_id, sha256, relative_path):
        return relative_path, "image/png"

    async def import_asset_owner(self, job_id):
        return self.owner


def _service(repository=None, work=None):
    return AcquisitionService(
        repository or _Repository(),
        _Catalog(),
        _Urls(),
        _Spend(),
        work or _Work(),
        _Filesystem(),
    )


PRINCIPAL = Principal(user_id=7, role="user")


@pytest.mark.asyncio
async def test_scrape_schedule_preserves_target_dedupe_key_and_payload():
    work = _Work(created=False)
    result = await _service(work=work).schedule_scrape(
        9,
        PRINCIPAL,
        ScheduleScrape(source_id=11, force=True, max_chapters=5),
    )

    assert work.call == {
        "novel_id": 9,
        "user_id": 7,
        "options": {"source_id": 11, "force": True, "max_chapters": 5},
        "idempotency_key": "scrape:novel9:source11:force1:max5",
    }
    assert result == {
        "status": "success",
        "message": "A scrape for this target is already running.",
        "job_id": 73,
        "deduped": True,
    }


@pytest.mark.asyncio
async def test_update_source_missing_target_is_not_found():
    repository = _Repository()
    repository.exists = False
    with pytest.raises(NotFound, match="Source not found"):
        await _service(repository=repository).update_source(
            9, 11, PRINCIPAL, {"label": "official"}
        )


@pytest.mark.asyncio
async def test_import_asset_does_not_disclose_another_users_job():
    repository = _Repository()
    repository.owner = ImportAssetOwner(99, {})
    with pytest.raises(NotFound, match="Import job not found"):
        await _service(repository=repository).import_job_asset(
            31, f"{'a' * 64}.png", PRINCIPAL
        )


@pytest.mark.asyncio
async def test_import_cover_sha_restricts_staged_asset():
    repository = _Repository()
    repository.owner = ImportAssetOwner(7, {"cover_sha": "b" * 64})
    with pytest.raises(NotFound, match="Asset not found"):
        await _service(repository=repository).import_job_asset(
            31, f"{'a' * 64}.png", PRINCIPAL
        )


@pytest.mark.parametrize(
    "filename",
    ["../secret.png", "nested/asset.png", f"{'a' * 64}.svg", "not-a-hash.png"],
)
def test_asset_filename_boundary_rejects_traversal_and_unapproved_names(filename):
    with pytest.raises(NotFound, match="Asset not found"):
        AcquisitionAssetFilesystem().normalize_filename(filename)


def test_asset_filename_boundary_canonicalizes_hash_and_jpeg_extension():
    sha256, extension, safe_name = AcquisitionAssetFilesystem().normalize_filename(
        f"{'A' * 64}.JPEG"
    )
    assert sha256 == "a" * 64
    assert extension == "jpg"
    assert safe_name == f"{'a' * 64}.jpg"
