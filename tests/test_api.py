"""End-to-end tests for the async public API over a writable in-memory store.

Exercises the full create → open → edit → save and compose-via-reference flows,
plus inlining and delete, through the real `open`/`create`/`save`/`save_inlined`/
`delete` verbs.
"""

from __future__ import annotations

import ngio_collections.api._api as aio
from ngio_collections.api import new_node
from ngio_collections.models.attributes import WellAttribute

DATA = "/data"


class _MemoryStore:
    """A writable in-memory store (url -> bytes)."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def get(self, url: str) -> bytes:
        try:
            return self.files[url]
        except KeyError as exc:
            raise FileNotFoundError(url) from exc

    async def put(self, url: str, data: bytes) -> None:
        self.files[url] = data

    async def delete(self, url: str) -> None:
        self.files.pop(url, None)


async def test_create_open_edit_save_roundtrip() -> None:
    store = _MemoryStore()
    root = new_node("collection", id="root").add(
        new_node("multiscale", id="img", attributes={"role": "raw"})
    )
    await aio.create(f"{DATA}/c.json", root, store)

    opened = await aio.open(f"{DATA}/c.json", store)
    assert not opened.is_detached and opened.document_url == f"{DATA}/c.json"
    assert opened.find("img").attributes["role"] == "raw"

    edited = opened.find("img").set_attrs({"role": "edited"})
    await aio.save(edited, store)

    reopened = await aio.open(f"{DATA}/c.json", store)
    assert reopened.find("img").attributes["role"] == "edited"


async def test_compose_via_reference_then_open_and_inline() -> None:
    store = _MemoryStore()
    # child document
    image = new_node("multiscale", id="image", attributes={"role": "target"})
    stub = await aio.create(f"{DATA}/image.zarr", image, store)
    assert stub.is_reference

    # parent references the child, decorating the stub
    stub = stub.set_attrs({"role": "raw"})
    parent = new_node("collection", id="root").add_ref(stub)
    await aio.create(f"{DATA}/c.json", parent, store)

    # open: the cross-document child stays a reference
    opened = await aio.open(f"{DATA}/c.json", store)
    assert opened.children()[0].is_reference

    # open_inlined: the child is spliced in, stub attributes overlay (stub wins)
    inlined = await aio.open_inlined(f"{DATA}/c.json", store)
    image_node = inlined.find("image")
    assert image_node is not None and not image_node.is_reference
    assert image_node.attributes["role"] == "raw"  # stub overlay wins


async def test_save_inlined_snapshots_to_one_document() -> None:
    store = _MemoryStore()
    image = new_node("multiscale", id="image", attributes={"role": "x"})
    stub = await aio.create(f"{DATA}/image.zarr", image, store)
    parent = new_node("collection", id="root").add_ref(stub)
    await aio.create(f"{DATA}/c.json", parent, store)

    view = await aio.open_inlined(f"{DATA}/c.json", store)
    await aio.save_inlined(view, f"{DATA}/flat.json", store)

    flat = await aio.open(f"{DATA}/flat.json", store)
    assert flat.find("image") is not None  # embedded inline now
    assert not flat.find("image").is_reference


async def test_delete_removes_document() -> None:
    store = _MemoryStore()
    root = new_node("collection", id="root").add(new_node("multiscale", id="img"))
    await aio.create(f"{DATA}/c.json", root, store)
    opened = await aio.open(f"{DATA}/c.json", store)
    affected = await aio.delete(opened, store)
    assert affected == [f"{DATA}/c.json"]
    assert f"{DATA}/c.json" not in store.files


async def test_create_refuses_existing_without_overwrite() -> None:
    import pytest

    from ngio_collections.models._config import NodeStateError

    store = _MemoryStore()
    root = new_node("collection", id="root")
    await aio.create(f"{DATA}/c.json", root, store)
    with pytest.raises(NodeStateError):
        await aio.create(f"{DATA}/c.json", new_node("collection", id="other"), store)
