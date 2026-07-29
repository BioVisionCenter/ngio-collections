"""FsspecStore: default backend for anything remote (optional dependency)."""

from __future__ import annotations

from typing import Any


class FsspecStore:
    """Store backed by an fsspec `AsyncFileSystem`.

    Recommended default for remote collections: one dependency brings
    http/s3/gcs/local and protocol dispatch. Requires the `fsspec` extra
    (`pip install ngio-collections[fsspec]`).

    Args:
        protocol: fsspec protocol name (e.g. `"https"`, `"s3"`).
        read_only: Reject `put()` with StoreReadOnlyError when True.
        **storage_options: Passed through to the fsspec filesystem.
    """

    def __init__(
        self, protocol: str, *, read_only: bool = False, **storage_options: Any
    ) -> None:
        try:
            import fsspec  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "FsspecStore requires the optional 'fsspec' dependency; "
                "install with: pip install ngio-collections[fsspec]"
            ) from exc
        self.protocol = protocol
        self.read_only = read_only
        self.storage_options = storage_options

    async def get(self, url: str) -> dict[str, Any]:
        """Return the document stored at `url`.

        Args:
            url: Absolute URL of the resource to fetch.

        Returns:
            The document's parsed JSON content.

        Raises:
            FileNotFoundError: If no resource exists at `url`.
            NotImplementedError: Until the fsspec backend is fully implemented.
        """
        raise NotImplementedError

    async def put(
        self, url: str, data: dict[str, Any], *, overwrite: bool = False
    ) -> None:
        """Write `data` at `url`.

        Args:
            url: Absolute URL of the destination.
            data: The document's JSON content to write.
            overwrite: Whether to replace an existing entry at `url`.

        Raises:
            StoreReadOnlyError: If the store was created with `read_only=True`.
            StoreDuplicateValueError: If an entry already exists at `url` and
                `overwrite` is `False`.
            NotImplementedError: Until the fsspec backend is fully implemented.
        """
        raise NotImplementedError

    async def delete(self, url: str) -> None:
        """Delete the object at `url`; idempotent.

        Args:
            url: Absolute URL of the resource to delete.

        Raises:
            StoreReadOnlyError: If the store was created with `read_only=True`.
        """
        raise NotImplementedError
