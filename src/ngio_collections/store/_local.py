"""Zero-dependency local filesystem store."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname


def _to_path(url: str) -> Path:
    """Return the filesystem `Path` for a plain path or `file://` URL.

    Args:
        url: A plain filesystem path string or a `file://` URL.

    Returns:
        Corresponding `pathlib.Path` object.
    """
    if url.startswith("file://"):
        return Path(url2pathname(urlparse(url).path))
    return Path(url)


class LocalStore:
    """Writable store over plain filesystem paths and `file://` URLs."""

    async def get(self, url: str) -> bytes:
        """Return the raw bytes of the file at `url`.

        Args:
            url: Filesystem path or `file://` URL to read.

        Returns:
            Raw bytes content of the file.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        return _to_path(url).read_bytes()

    async def put(self, url: str, data: bytes) -> None:
        """Write `data` to `url`, creating parent directories as needed.

        Args:
            url: Destination filesystem path or `file://` URL.
            data: Raw bytes to write.
        """
        path = _to_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def delete(self, url: str) -> None:
        """Delete the file at `url`; idempotent (a missing file is fine).

        Args:
            url: Filesystem path or `file://` URL to delete.
        """
        _to_path(url).unlink(missing_ok=True)
