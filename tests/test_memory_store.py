"""Tests for `MemoryStore`: the store contract plus a hermetic API round-trip."""

from __future__ import annotations

import pytest

import ngio_collections.api._api as aio
from ngio_collections.api import (
    MemoryStore,
    ReadableStore,
    StoreReadOnlyError,
    WritableStore,
    new_node,
)


async def test_store_contract() -> None:
    store = MemoryStore({"/a.json": b"seed"})
    assert isinstance(store, ReadableStore) and isinstance(store, WritableStore)

    assert await store.get("/a.json") == b"seed"
    with pytest.raises(FileNotFoundError):
        await store.get("/missing.json")

    await store.put("/b.json", b"data")
    assert await store.get("/b.json") == b"data"
    assert dict(store.items()) == {"/a.json": b"seed", "/b.json": b"data"}
    assert "/b.json" in store and len(store) == 2

    await store.delete("/b.json")
    await store.delete("/b.json")  # idempotent
    assert "/b.json" not in store


async def test_initial_mapping_is_copied() -> None:
    seed = {"/a.json": b"seed"}
    store = MemoryStore(seed)
    seed["/a.json"] = b"mutated"
    assert await store.get("/a.json") == b"seed"


async def test_read_only_rejects_writes() -> None:
    store = MemoryStore({"/a.json": b"seed"}, read_only=True)
    assert await store.get("/a.json") == b"seed"
    with pytest.raises(StoreReadOnlyError):
        await store.put("/b.json", b"data")
    with pytest.raises(StoreReadOnlyError):
        await store.delete("/a.json")


async def test_read_only_fails_early_through_the_api() -> None:
    store = MemoryStore(read_only=True)
    with pytest.raises(StoreReadOnlyError):
        await aio.create("/c.json", new_node("collection", id="root"), store)


async def test_hermetic_create_open_save_roundtrip() -> None:
    store = MemoryStore()
    image = new_node("multiscale", id="image", attributes={"role": "raw"})
    stub = await aio.create("/data/image.zarr", image, store)
    root = new_node("collection", id="root", children=[stub])
    await aio.create("/data/c.json", root, store)

    opened = await aio.open("/data/c.json", store)
    edited = opened.find("image").set_attrs({"role": "edited"})
    await aio.save(edited, store)

    inlined = await aio.open_inlined("/data/c.json", store)
    assert inlined.find("image").attributes["role"] == "edited"
    assert {url for url, _ in store.items()} == {
        "/data/c.json",
        "/data/image.zarr/zarr.json",
    }
