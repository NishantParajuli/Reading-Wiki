from __future__ import annotations

import os
import re
from pathlib import Path

from novelwiki.kernel.errors import NotFound

from ...application.ports import AssetFile
from .importer import storage

_ASSET_FILENAME_RE = re.compile(
    r"^(?P<sha>[a-fA-F0-9]{64})\.(?P<ext>[A-Za-z0-9]+)$"
)


class AcquisitionAssetFilesystem:
    """Security boundary for all Acquisition-served filesystem paths."""

    def normalize_filename(self, filename: str) -> tuple[str, str, str]:
        if (
            os.path.basename(filename) != filename
            or "/" in filename
            or "\\" in filename
        ):
            raise NotFound("Asset not found.")
        match = _ASSET_FILENAME_RE.fullmatch(filename or "")
        if not match:
            raise NotFound("Asset not found.")
        sha256 = match.group("sha").lower()
        extension = match.group("ext").lower()
        if extension == "jpeg":
            extension = "jpg"
        if extension not in storage.ALLOWED_ASSET_EXTS:
            raise NotFound("Asset not found.")
        return sha256, extension, f"{sha256}.{extension}"

    def novel_relative_path(
        self, novel_id: int, sha256: str, extension: str
    ) -> str:
        return storage.asset_rel(novel_id, sha256, extension)

    def novel_file(
        self, novel_id: int, safe_name: str, mime: str | None
    ) -> AssetFile:
        root = storage.asset_file_path(novel_id, "__root__").parent
        path = self._safe_child(root, storage.asset_file_path(novel_id, safe_name))
        return self._existing(path, mime)

    def staged_file(self, job_id: int, safe_name: str) -> AssetFile:
        root = storage.staged_asset_file_path(job_id, "__root__").parent
        path = self._safe_child(root, storage.staged_asset_file_path(job_id, safe_name))
        return self._existing(
            path, storage.mime_from_ext(safe_name.rsplit(".", 1)[1])
        )

    @staticmethod
    def _safe_child(root: Path, child: Path) -> Path:
        resolved_root = root.resolve()
        resolved_child = child.resolve()
        if (
            resolved_child != resolved_root
            and resolved_root not in resolved_child.parents
        ):
            raise NotFound("Asset not found.")
        return resolved_child

    @staticmethod
    def _existing(path: Path, mime: str | None) -> AssetFile:
        if not path.is_file():
            raise NotFound("Asset not found.")
        return AssetFile(
            path=path,
            mime=mime or storage.mime_from_ext(path.suffix),
        )
