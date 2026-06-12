"""Zero-dependency local filesystem store."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname


def _to_path(url: str) -> Path:
    """Filesystem path for a plain path or ``file://`` URL."""
    if url.startswith("file://"):
        return Path(url2pathname(urlparse(url).path))
    return Path(url)


class LocalStore:
    """Writable store over plain filesystem paths and ``file://`` URLs."""

    async def get(self, url: str) -> bytes:
        """Bytes at ``url``; raises FileNotFoundError if absent."""
        return _to_path(url).read_bytes()

    async def put(self, url: str, data: bytes) -> None:
        """Write ``data`` at ``url``, creating parent directories."""
        path = _to_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
