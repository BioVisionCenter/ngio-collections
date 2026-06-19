"""FsspecStore: default backend for anything remote (optional dependency)."""

from __future__ import annotations

from typing import Any


class FsspecStore:
    """Store backed by an fsspec ``AsyncFileSystem``.

    Recommended default for remote collections: one dependency brings
    http/s3/gcs/local and protocol dispatch. Requires the ``fsspec`` extra
    (``pip install ngio-collections[fsspec]``).

    Args:
        protocol: fsspec protocol name (e.g. ``"https"``, ``"s3"``).
        read_only: Reject ``put()`` with StoreReadOnlyError when True.
        **storage_options: Passed through to the fsspec filesystem.
    """

    def __init__(
        self, protocol: str, *, read_only: bool = False, **storage_options: Any
    ) -> None:
        try:
            import fsspec  # noqa: F401  # ty: ignore[unresolved-import]
        except ImportError as exc:
            raise ImportError(
                "FsspecStore requires the optional 'fsspec' dependency; "
                "install with: pip install ngio-collections[fsspec]"
            ) from exc
        self.protocol = protocol
        self.read_only = read_only
        self.storage_options = storage_options

    async def get(self, url: str) -> bytes:
        """Bytes at ``url``; raises FileNotFoundError if absent."""
        raise NotImplementedError

    async def put(self, url: str, data: bytes) -> None:
        """Write ``data`` at ``url``; StoreReadOnlyError when read-only."""
        raise NotImplementedError

    async def delete(self, url: str) -> None:
        """Delete the object at ``url``; StoreReadOnlyError when read-only."""
        raise NotImplementedError
