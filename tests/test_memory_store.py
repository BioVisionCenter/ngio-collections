"""Tests for `MemoryStore`: the store contract plus a hermetic API round-trip."""

from __future__ import annotations

import pytest

import ngio_collections.api._api as aio
from ngio_collections.api import (
    AsyncReadableStore,
    AsyncWritableStore,
    MemoryStore,
    StoreDuplicateValueError,
    StoreReadOnlyError,
)
from tests._builders import collection, multiscale
from tests.conftest import mk, requires_pydantic


async def test_store_contract() -> None:
    store = MemoryStore({"/a.json": {"seed": True}})
    assert isinstance(store, AsyncReadableStore) and isinstance(
        store, AsyncWritableStore
    )
    assert await store.get("/a.json") == {"seed": True}
    with pytest.raises(FileNotFoundError):
        await store.get("/missing.json")
    await store.put("/b.json", {"data": True})
    items = [item async for item in store.items()]
    assert dict(items) == {"/a.json": {"seed": True}, "/b.json": {"data": True}}
    assert (await store.contains("/b.json")) and (await store.size()) == 2
    await store.delete("/b.json")
    await store.delete("/b.json")  # idempotent
    assert not (await store.contains("/b.json"))


async def test_put_rejects_duplicate_url_without_overwrite() -> None:
    store = MemoryStore({"/a.json": {"seed": True}})
    with pytest.raises(StoreDuplicateValueError):
        await store.put("/a.json", {"clobber": True})
    await store.put("/a.json", {"clobber": True}, overwrite=True)
    assert await store.get("/a.json") == {"clobber": True}


async def test_read_only_rejects_writes_and_fails_early_through_the_api() -> None:
    store = MemoryStore({"/a.json": {"seed": True}}, read_only=True)
    with pytest.raises(StoreReadOnlyError):
        await store.put("/b.json", {"data": True})
    with pytest.raises(StoreReadOnlyError):
        await aio.create("/c.json", collection(1), store)


@requires_pydantic  # validators / `.scales` read through the typed models
async def test_hermetic_create_open_save_roundtrip() -> None:
    store = MemoryStore()
    stub = await aio.create("/data/image.zarr", multiscale(2, name="raw"), store)
    await aio.create("/data/c.json", collection(1).add_external(stub), store)
    opened = await aio.open("/data/c.json", store)
    await aio.save(opened.find(mk(2)).rename("edited"), store)
    view = await aio.open_resolved("/data/c.json", store)
    assert view.find(mk(2)).name == "edited" and len(view.find(mk(2)).scales) == 2
    urls = {url async for url, _ in store.items()}
    assert urls == {"/data/c.json", "/data/image.zarr/zarr.json"}
