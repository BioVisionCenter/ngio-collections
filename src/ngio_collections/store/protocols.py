"""Store protocols: the only IO boundary of the package.

Stores are URL-addressed, not rooted (DESIGN.md §2.5): ``get(url)`` takes a
full URL. This makes mixed-store routing pure composition and keeps the
resolver's document cache globally coherent.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class StoreReadOnlyError(PermissionError):
    """Raised by ``put()`` on a read-only backend. Part of the contract."""


@runtime_checkable
class ReadableStore(Protocol):
    async def get(self, url: str) -> bytes:
        """Bytes at ``url``. MUST raise FileNotFoundError if absent."""
        ...


@runtime_checkable
class WritableStore(ReadableStore, Protocol):
    async def put(self, url: str, data: bytes) -> None:
        """Write ``data`` at ``url``, creating parents as needed."""
        ...
