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
    new_node,
)
from ngio_collections.io.store._adapt import as_async


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
        if self.read_only:
            raise StoreReadOnlyError("SyncDictStore is read-only")
        self._data.pop(url, None)


def test_sync_store_satisfies_the_sync_protocols() -> None:
    store = SyncDictStore()
    assert isinstance(store, SyncReadableStore)
    assert isinstance(store, SyncWritableStore)


def test_as_async_wraps_a_sync_store() -> None:
    store = SyncDictStore()
    wrapped = as_async(store)
    assert isinstance(wrapped, AsyncReadableStore)
    assert isinstance(wrapped, AsyncWritableStore)


async def test_as_async_leaves_an_already_async_store_untouched() -> None:
    from ngio_collections.io.store import MemoryStore

    store = MemoryStore()
    assert as_async(store) is store


async def test_as_async_forwards_read_only() -> None:
    wrapped = as_async(SyncDictStore(read_only=True))
    with pytest.raises(StoreReadOnlyError):
        await aio.create("/c.json", new_node("collection", id="root"), wrapped)


async def test_sync_store_roundtrips_through_the_async_api() -> None:
    store = SyncDictStore()
    image = new_node("multiscale", id="image", attributes={"role": "raw"})
    stub = await aio.create("/data/image.zarr", image, store)
    root = new_node("collection", id="root", children=[stub])
    await aio.create("/data/c.json", root, store)

    opened = await aio.open("/data/c.json", store)
    edited = opened.find("image").set_attrs({"role": "edited"})
    await aio.save(edited, store)

    inlined = await aio.open_inlined("/data/c.json", store)
    assert inlined.find("image").attributes["role"] == "edited"
