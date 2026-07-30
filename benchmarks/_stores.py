"""Benchmark-only store wrappers.

`DelayStore` injects a fixed per-read latency so the payoff of concurrent
document I/O is measurable deterministically — independent of the OS page cache
(which makes warm local reads ~µs and hides the win). It models the real target:
high-latency / remote stores. With sequential reads the cost is ~``N * delay``;
with `Resolver(prefetch_concurrency=k)` it drops toward ~``ceil(N/k) * delay``.
"""

from __future__ import annotations

import asyncio

from ngio_collections._types import JSONValue
from ngio_collections.io.store import AsyncReadableStore, AsyncWritableStore


class DelayStore:
    """Wrap a store, sleeping `delay_s` before each `get` (simulated read latency)."""

    def __init__(self, inner: AsyncReadableStore, delay_s: float) -> None:
        """Wrap `inner`, adding `delay_s` seconds of latency to every `get`."""
        self.inner = inner
        self.delay_s = delay_s

    async def get(self, url: str) -> dict[str, JSONValue]:
        """Sleep `delay_s`, then delegate the read to the wrapped store."""
        await asyncio.sleep(self.delay_s)
        return await self.inner.get(url)

    async def put(self, url: str, data: dict[str, JSONValue]) -> None:
        """Delegate the write to the wrapped store (no injected delay)."""
        await _writable(self.inner).put(url, data)

    async def delete(self, url: str) -> None:
        """Delegate the delete to the wrapped store (no injected delay)."""
        await _writable(self.inner).delete(url)


def _writable(store: AsyncReadableStore) -> AsyncWritableStore:
    """Narrow `store` to a `WritableStore`, raising if it is read-only."""
    if not isinstance(store, AsyncWritableStore):
        raise TypeError(f"{type(store).__name__} is not writable")
    return store
