from __future__ import annotations

import hashlib
from pathlib import Path


class AvatarFilesystem:
    def __init__(self, asset_dir: str):
        self._asset_dir = Path(asset_dir)

    def save(self, user_id: int, data: bytes, extension: str) -> str:
        extension = (extension or "png").lower().lstrip(".")
        extension = "jpg" if extension == "jpeg" else extension
        if extension not in {"jpg", "png", "webp", "gif"}:
            extension = "png"
        relative = Path("_users") / str(user_id) / f"{hashlib.sha256(data).hexdigest()[:16]}.{extension}"
        target = self._asset_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return relative.as_posix()
