"""Zero-dependency local filesystem store."""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from ngio_collections.io.store._protocols import StoreDuplicateValueError
from ngio_collections.models._paths import split_scheme


def _to_path(url: str) -> Path:
    """Return the filesystem `Path` for a plain path or `file://` URL.

    Scheme detection is shared with the path layer (`_paths.split_scheme`) so
    there is one notion of "local vs `file://`" across the package.

    Args:
        url: A plain filesystem path string or a `file://` URL.

    Returns:
        Corresponding `pathlib.Path` object.
    """
    if split_scheme(url)[0] == "file":
        return Path(url2pathname(urlparse(url).path))
    return Path(url)


class LocalStore:
    """Writable store over plain filesystem paths and `file://` URLs."""

    async def get(self, url: str) -> bytes:
        """Return the raw bytes of the file at `url`.

        The blocking read runs on a worker thread (`asyncio.to_thread`) so that
        concurrent `get` calls overlap instead of serializing on the event loop —
        the file read releases the GIL. This is what lets `Resolver`'s prefetch
        pass fan out many document reads at once.

        Args:
            url: Filesystem path or `file://` URL to read.

        Returns:
            Raw bytes content of the file.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        return await asyncio.to_thread(_to_path(url).read_bytes)

    async def put(self, url: str, data: bytes, *, overwrite: bool = False) -> None:
        """Write `data` to `url`, creating parent directories as needed.

        Args:
            url: Destination filesystem path or `file://` URL.
            data: Raw bytes to write.
            overwrite: Whether to replace an existing file at `url`.

        Raises:
            StoreDuplicateValueError: If a file already exists at `url` and
                `overwrite` is `False`.
        """
        path = _to_path(url)
        if not overwrite and path.exists():
            raise StoreDuplicateValueError(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def delete(self, url: str) -> None:
        """Delete the file at `url`; idempotent (a missing file is fine).

        Args:
            url: Filesystem path or `file://` URL to delete.
        """
        _to_path(url).unlink(missing_ok=True)
