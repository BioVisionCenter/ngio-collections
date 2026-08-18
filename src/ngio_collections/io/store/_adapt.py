"""Adapts a sync store to the async store protocols.

The resolver and API layer are async throughout (`ngio-v5-architecture`); this
lets a caller hand in a plain synchronous store — e.g. one wrapping a
synchronous database client — without writing any `asyncio` themselves. Each
call is offloaded to a worker thread with `asyncio.to_thread`, the same trick
`LocalStore` already uses for its own filesystem calls.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import cast

from ngio_collections._types import JSONValue
from ngio_collections.io.store._protocols import (
    AsyncReadableStore,
    SyncReadableStore,
    SyncWritableStore,
)


class _AsyncFromSyncReadable:
    """Async-protocol view of a `SyncReadableStore`, offloaded to a thread."""

    def __init__(self, store: SyncReadableStore) -> None:
        self._store = store

    @property
    def read_only(self) -> bool:
        """Whether the wrapped store rejects writes."""
        return getattr(self._store, "read_only", False)

    async def get(self, url: str) -> dict[str, JSONValue]:
        """See `AsyncReadableStore.get`."""
        return await asyncio.to_thread(self._store.get, url)


class _AsyncFromSyncWritable(_AsyncFromSyncReadable):
    """Async-protocol view of a `SyncWritableStore`, offloaded to a thread.

    Constructed only via `as_async` after it has confirmed `store` implements
    `SyncWritableStore`, hence the `cast` below.
    """

    async def put(
        self, url: str, data: dict[str, JSONValue], *, overwrite: bool = False
    ) -> None:
        """See `AsyncWritableStore.put`."""
        store = cast(SyncWritableStore, self._store)
        await asyncio.to_thread(store.put, url, data, overwrite=overwrite)

    async def delete(self, url: str) -> None:
        """See `AsyncWritableStore.delete`."""
        store = cast(SyncWritableStore, self._store)
        await asyncio.to_thread(store.delete, url)


def as_async(store: AsyncReadableStore | SyncReadableStore) -> AsyncReadableStore:
    """Return `store` viewed through the async protocol, adapting it if needed.

    A store that already implements the async protocol (`get` is a coroutine
    function) is returned unchanged. A sync store is wrapped so every call
    runs on a worker thread, keeping the resolver and API layer's engine
    async-only regardless of which protocol the backend implements.

    Args:
        store: Either a `AsyncReadableStore` or a `SyncReadableStore` (and,
            for writes, their writable counterparts).

    Returns:
        `store` itself if already async, otherwise a thread-offloading wrapper
        around it that also implements `put`/`delete` when `store` does.
    """
    if inspect.iscoroutinefunction(getattr(store, "get", None)):
        return cast(AsyncReadableStore, store)
    if isinstance(store, SyncWritableStore):
        return _AsyncFromSyncWritable(store)
    return _AsyncFromSyncReadable(cast(SyncReadableStore, store))
