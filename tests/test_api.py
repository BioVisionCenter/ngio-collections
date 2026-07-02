"""End-to-end tests for the async public API over a writable in-memory store.

Exercises the full create → open → edit → save and compose-via-reference flows,
plus inlining and delete, through the real `open`/`create`/`save`/`save_inlined`/
`delete` verbs.
"""

from __future__ import annotations

import ngio_collections.api._api as aio
from ngio_collections.api import new_node
from ngio_collections.models._paths import ZarrPath
from ngio_collections.models._references import ReferenceObj
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


async def test_ref_stub_matches_create_stub() -> None:
    store = _MemoryStore()
    image = new_node("multiscale", id="image", name="Image")
    created_stub = await aio.create(f"{DATA}/image.zarr", image, store)

    # a stub minted from the opened node is the same shape create() returned
    opened = await aio.open(f"{DATA}/image.zarr", store)
    stub = opened.ref_stub()
    assert stub.is_reference and stub.is_detached
    assert stub.ref_path == created_stub.ref_path == f"{DATA}/image.zarr"
    assert stub.record.ref.id == "image"
    assert stub.type == "multiscale" and stub.name == "Image"

    # and it composes into a parent exactly like create()'s stub does
    parent = new_node("collection", id="root").add_ref(stub)
    await aio.create(f"{DATA}/c.json", parent, store)
    inlined = await aio.open_inlined(f"{DATA}/c.json", store)
    image_node = inlined.find("image")
    assert image_node is not None and not image_node.is_reference


async def test_children_literal_mixes_stub_and_embedded() -> None:
    store = _MemoryStore()
    image = new_node("multiscale", id="image", attributes={"role": "target"})
    stub = await aio.create(f"{DATA}/image.zarr", image, store)
    table = new_node("multiscale", id="table", attributes={"role": "table"})
    scene = new_node("collection", id="scene", children=[stub, table])
    await aio.create(f"{DATA}/scene.json", scene, store)

    inlined = await aio.open_inlined(f"{DATA}/scene.json", store)
    assert [n.id for n in inlined.children()] == ["image", "table"]
    assert inlined.find("image").attributes["role"] == "target"
    assert inlined.find("table").attributes["role"] == "table"


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


async def test_open_ref_resolves_subtree_across_documents() -> None:
    store = _MemoryStore()
    image = new_node("multiscale", id="image", attributes={"role": "target"})
    stub = await aio.create(f"{DATA}/image.zarr", image, store)
    parent = new_node("collection", id="root").add_ref(stub)
    await aio.create(f"{DATA}/c.json", parent, store)

    # Take a reference the way a user would: from the unresolved stub on disk.
    opened = await aio.open(f"{DATA}/c.json", store)
    ref = ReferenceObj(id="image", path=opened.children()[0].record.ref.path)

    node = await aio.open_ref(ref, opened.document_url, store)
    assert node.id == "image" and node.type == "multiscale"
    assert node.attributes["role"] == "target"
    # The opened subtree is editable (cross-doc, not inlined/read-only).
    assert node.tree.mode == "editable"


async def test_open_inlined_ref_resolves_nested_references() -> None:
    store = _MemoryStore()
    # leaf -> mid -> entry chain of single-child documents
    leaf = new_node("multiscale", id="leaf", attributes={"role": "deep"})
    leaf_stub = await aio.create(f"{DATA}/leaf.zarr", leaf, store)
    mid = new_node("collection", id="mid").add_ref(leaf_stub)
    mid_stub = await aio.create(f"{DATA}/mid.json", mid, store)
    entry = new_node("collection", id="root").add_ref(mid_stub)
    await aio.create(f"{DATA}/entry.json", entry, store)

    opened = await aio.open(f"{DATA}/entry.json", store)
    ref = ReferenceObj(id="mid", path=opened.children()[0].record.ref.path)

    view = await aio.open_inlined_ref(ref, opened.document_url, store)
    assert view.id == "mid" and view.tree.mode == "resolved"
    # The nested leaf reference was inlined too, not left as a stub.
    leaf_node = view.find("leaf")
    assert leaf_node is not None and not leaf_node.is_reference
    assert leaf_node.attributes["role"] == "deep"


async def test_open_ref_missing_id_raises_lookup_error() -> None:
    import pytest

    store = _MemoryStore()
    image = new_node("multiscale", id="image")
    await aio.create(f"{DATA}/image.zarr", image, store)
    ref = ReferenceObj(id="absent", path=ZarrPath(path=f"{DATA}/image.zarr"))
    with pytest.raises(LookupError):
        await aio.open_ref(ref, store=store)


async def test_open_ref_without_path_raises() -> None:
    import pytest

    from ngio_collections.models._config import NodeStateError

    with pytest.raises(NodeStateError):
        await aio.open_ref(ReferenceObj(id="image", path=None))


async def test_create_refuses_existing_without_overwrite() -> None:
    import pytest

    from ngio_collections.models._config import NodeStateError

    store = _MemoryStore()
    root = new_node("collection", id="root")
    await aio.create(f"{DATA}/c.json", root, store)
    with pytest.raises(NodeStateError):
        await aio.create(f"{DATA}/c.json", new_node("collection", id="other"), store)
