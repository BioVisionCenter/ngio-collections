"""Tests for `as_async`: a plain sync store used through the async API."""

from __future__ import annotations

import pytest

import ngio_collections.api._api as aio
from ngio_collections.api import (
    AsyncReadableStore,
    AsyncWritableStore,
    StoreDuplicateValueError,
    StoreReadOnlyError,
    SyncReadableStore,
    SyncWritableStore,
)
from ngio_collections.io.store._adapt import as_async
from tests._builders import collection, multiscale
from tests.conftest import mk


class SyncDictStore:
    """A minimal, fully synchronous `SyncWritableStore` over a plain dict."""

    def __init__(self, *, read_only: bool = False) -> None:
        self._data: dict[str, dict] = {}
        self.read_only = read_only

    def get(self, url: str) -> dict:
        try:
            return self._data[url]
        except KeyError as exc:
            raise FileNotFoundError(url) from exc

    def put(self, url: str, data: dict, *, overwrite: bool = False) -> None:
        if self.read_only:
            raise StoreReadOnlyError("SyncDictStore is read-only")
        if not overwrite and url in self._data:
            raise StoreDuplicateValueError(url)
        self._data[url] = data

    def delete(self, url: str) -> None:
        self._data.pop(url, None)


def test_sync_store_satisfies_the_sync_protocols_and_wraps() -> None:
    store = SyncDictStore()
    assert isinstance(store, SyncReadableStore) and isinstance(store, SyncWritableStore)
    wrapped = as_async(store)
    assert isinstance(wrapped, AsyncReadableStore) and isinstance(
        wrapped, AsyncWritableStore
    )


async def test_as_async_leaves_an_already_async_store_untouched() -> None:
    from ngio_collections.io.store import MemoryStore

    store = MemoryStore()
    assert as_async(store) is store


async def test_as_async_forwards_read_only() -> None:
    with pytest.raises(StoreReadOnlyError):
        await aio.create(
            "/c.json", collection(1), as_async(SyncDictStore(read_only=True))
        )


async def test_sync_store_roundtrips_through_the_async_api() -> None:
    store = SyncDictStore()
    stub = await aio.create("/data/image.zarr", multiscale(2), store)
    await aio.create("/data/c.json", collection(1).add_external(stub), store)
    opened = await aio.open("/data/c.json", store)
    await aio.save(opened.find(mk(2)).rename("edited"), store)
    view = await aio.open_resolved("/data/c.json", store)
    assert view.find(mk(2)).name == "edited" and not view.find(mk(2)).is_external
