"""Store protocols: the only IO boundary of the package.

Stores are URL-addressed, not rooted: `get(url)` takes a full URL. This makes
mixed-store routing pure composition and keeps the resolver's document cache
globally coherent.

The `url` here is the document's *bytes address* (the metadata file, e.g.
`.../group.zarr/zarr.json`) — distinct from the `ref_url` a reference stores to
locate that document (the group directory). The resolver derives one from the
other via `models/_paths.meta_url`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class StoreReadOnlyError(PermissionError):
    """Raised by `put()` on a read-only backend. Part of the contract."""


@runtime_checkable
class ReadableStore(Protocol):
    async def get(self, url: str) -> bytes:
        """Return the raw bytes stored at `url`.

        Args:
            url: Absolute URL of the resource to fetch.

        Returns:
            Raw bytes content of the resource.

        Raises:
            FileNotFoundError: If no resource exists at `url`.
        """
        ...


@runtime_checkable
class WritableStore(ReadableStore, Protocol):
    async def put(self, url: str, data: bytes) -> None:
        """Write `data` at `url`, creating parents as needed.

        Args:
            url: Absolute URL of the destination.
            data: Raw bytes to write.
        """
        ...

    async def delete(self, url: str) -> None:
        """Delete the object at `url`; idempotent (missing URL is not an error).

        Args:
            url: Absolute URL of the resource to delete.
        """
        ...
