"""End-to-end tests for the async public API over a writable in-memory store.

Exercises the full create → open → edit → save and compose-via-reference flows,
plus inlining, externalize and delete, through the real verbs.
"""

from __future__ import annotations

import pytest
from conftest import uid

import ngio_collections.api._api as aio
from ngio_collections.api import MemoryStore, new_node
from ngio_collections.models._config import NodeStateError
from ngio_collections.models._paths import ZarrPath
from ngio_collections.models._references import ReferenceObj

DATA = "/data"


def _collection(name: str, **kw) -> object:
    return new_node("collection", id=uid(name), name=name, **kw)


def _image(name: str, **body) -> object:
    return new_node("multiscale", id=uid(name), name=name, attributes=body)


async def test_create_open_edit_save_roundtrip() -> None:
    store = MemoryStore()
    root = _collection("root").add(_image("img", role="raw"))
    await aio.create(f"{DATA}/c.json", root, store)

    opened = await aio.open(f"{DATA}/c.json", store)
    assert not opened.is_detached and opened.document_url == f"{DATA}/c.json"
    assert opened.find(uid("img")).attributes["role"] == "raw"

    edited = opened.find(uid("img")).set_attrs({"role": "edited"})
    await aio.save(edited, store)

    reopened = await aio.open(f"{DATA}/c.json", store)
    assert reopened.find(uid("img")).attributes["role"] == "edited"


async def test_compose_via_reference_then_open_and_inline() -> None:
    store = MemoryStore()
    stub = await aio.create(f"{DATA}/image.zarr", _image("image", role="target"), store)
    assert stub.is_reference and stub.is_detached
    assert stub.id is None and stub.name is None and not stub.attributes
    assert stub.record.ref.ref == uid("image")
    assert stub.ref_path == f"{DATA}/image.zarr"

    parent = _collection("root").add_ref(stub)
    assert parent.find(uid("image")) is None  # a pointer declares nothing
    assert parent.tree.referrers(uid("image"))
    await aio.create(f"{DATA}/c.json", parent, store)

    # open: the cross-document child stays a reference, reached structurally
    (child,) = (await aio.open(f"{DATA}/c.json", store)).children()
    assert child.is_reference and child.id is None
    assert child.record.ref.ref == uid("image") and child.ref_path == "./image.zarr"
    assert child.ref().model_dump() == ReferenceObj(
        type="multiscale", ref=uid("image"), path=ZarrPath(href="./image.zarr")
    ).model_dump()

    # open_inlined: the declaration takes the reference's place, verbatim
    inlined = await aio.open_inlined(f"{DATA}/c.json", store)
    image_node = inlined.find(uid("image"))
    assert image_node is not None and not image_node.is_reference
    assert image_node.name == "image" and image_node.attributes == {"role": "target"}
    assert image_node.document_url == f"{DATA}/image.zarr/zarr.json"


async def test_ref_stub_matches_create_stub() -> None:
    store = MemoryStore()
    created_stub = await aio.create(f"{DATA}/image.zarr", _image("image"), store)

    opened = await aio.open(f"{DATA}/image.zarr", store)
    stub = opened.ref_stub()
    assert stub.record == created_stub.record
    assert stub.type == "multiscale" and stub.id is None
    assert opened.ref() == ReferenceObj(
        type="multiscale", ref=uid("image"), path=ZarrPath(href=f"{DATA}/image.zarr")
    )

    parent = _collection("root").add_ref(stub)
    await aio.create(f"{DATA}/c.json", parent, store)
    inlined = await aio.open_inlined(f"{DATA}/c.json", store)
    assert inlined.find(uid("image")) is not None


async def test_reference_child_can_be_removed_structurally() -> None:
    store = MemoryStore()
    stub = await aio.create(f"{DATA}/image.zarr", _image("image"), store)
    await aio.create(f"{DATA}/c.json", _collection("root").add_ref(stub), store)

    reopened = await aio.open(f"{DATA}/c.json", store)
    (child,) = reopened.children()
    pruned = child.remove()
    assert pruned.children() == ()
    await aio.save(pruned, store)
    assert (await aio.open(f"{DATA}/c.json", store)).children() == ()


async def test_edits_on_a_reference_node_raise() -> None:
    stub = new_node(
        "multiscale",
        ref=aio.Reference(ref=uid("image"), path=ZarrPath(href="/img.zarr")),
    )
    with pytest.raises(NodeStateError):
        stub.set_attrs({"x": 1})
    with pytest.raises(NodeStateError):
        stub.rename("x")
    with pytest.raises(NodeStateError):
        stub.drop_attrs("x")
    with pytest.raises(NodeStateError):
        stub.require_id()


async def test_children_literal_mixes_stub_and_embedded() -> None:
    store = MemoryStore()
    stub = await aio.create(f"{DATA}/image.zarr", _image("image", role="target"), store)
    table = _image("table", role="table")
    scene = _collection("scene", children=[stub, table])
    await aio.create(f"{DATA}/scene.json", scene, store)

    inlined = await aio.open_inlined(f"{DATA}/scene.json", store)
    assert [n.id for n in inlined.children()] == [uid("image"), uid("table")]
    assert inlined.find(uid("image")).attributes["role"] == "target"
    assert inlined.find(uid("table")).attributes["role"] == "table"


async def test_save_inlined_snapshots_to_one_document() -> None:
    store = MemoryStore()
    stub = await aio.create(f"{DATA}/image.zarr", _image("image", role="x"), store)
    await aio.create(f"{DATA}/c.json", _collection("root").add_ref(stub), store)

    view = await aio.open_inlined(f"{DATA}/c.json", store)
    await aio.save_inlined(view, f"{DATA}/flat.json", store)

    flat = await aio.open(f"{DATA}/flat.json", store)
    assert flat.find(uid("image")) is not None  # embedded inline now
    assert not flat.find(uid("image")).is_reference


async def test_subtree_of_inlined_node_is_detached() -> None:
    store = MemoryStore()
    stub = await aio.create(f"{DATA}/image.zarr", _image("image", role="x"), store)
    await aio.create(f"{DATA}/c.json", _collection("root").add_ref(stub), store)

    view = await aio.open_inlined(f"{DATA}/c.json", store)
    sub = view.find(uid("image")).subtree()
    assert sub.is_detached and sub.id == uid("image")


async def test_delete_removes_document() -> None:
    store = MemoryStore()
    root = _collection("root").add(_image("img"))
    await aio.create(f"{DATA}/c.json", root, store)
    opened = await aio.open(f"{DATA}/c.json", store)
    affected = await aio.delete(opened, store)
    assert affected == [f"{DATA}/c.json"]
    assert not (await store.contains(f"{DATA}/c.json"))


async def test_delete_refuses_a_reference_node() -> None:
    store = MemoryStore()
    stub = await aio.create(f"{DATA}/image.zarr", _image("image"), store)
    await aio.create(f"{DATA}/c.json", _collection("root").add_ref(stub), store)
    (child,) = (await aio.open(f"{DATA}/c.json", store)).children()
    with pytest.raises(NodeStateError):
        await aio.delete(child, store)
    # ... but the inlined declaration knows its own document
    view = await aio.open_inlined(f"{DATA}/c.json", store)
    assert await aio.delete(view.find(uid("image")), store) == [
        f"{DATA}/image.zarr/zarr.json"
    ]


async def test_externalize_splits_node_into_own_document() -> None:
    store = MemoryStore()
    root = _collection(
        "root",
        children=[
            _collection("crop", children=[_image("img", role="raw")]),
            _image("table"),
        ],
    )
    await aio.create(f"{DATA}/c.json", root, store)
    before = await aio.open_inlined(f"{DATA}/c.json", store)

    opened = await aio.open(f"{DATA}/c.json", store)
    updated = await aio.externalize(opened.find(uid("crop")), f"{DATA}/crop.zarr", store)

    # returned root: a reference in place of the node, same sibling position
    crop, table = updated.children()
    assert crop.is_reference and crop.id is None
    assert crop.record.ref.ref == uid("crop") and crop.ref_path == f"{DATA}/crop.zarr"
    assert table.id == uid("table")
    assert updated.find(uid("img")) is None

    # the new document holds the subtree
    crop_doc = await aio.open(f"{DATA}/crop.zarr", store)
    assert [n.id for n in crop_doc.walk()] == [uid("crop"), uid("img")]
    assert crop_doc.find(uid("img")).attributes["role"] == "raw"

    # the home document was rewritten; the inlined view is unchanged
    reopened = await aio.open(f"{DATA}/c.json", store)
    assert reopened.children()[0].is_reference
    after = await aio.open_inlined(f"{DATA}/c.json", store)
    assert [(n.id, dict(n.attributes)) for n in after.walk()] == [
        (n.id, dict(n.attributes)) for n in before.walk()
    ]


async def test_externalize_rejects_invalid_targets() -> None:
    store = MemoryStore()
    stub = await aio.create(f"{DATA}/image.zarr", _image("image"), store)
    root = _collection("root", children=[_image("img")]).add_ref(stub)
    await aio.create(f"{DATA}/c.json", root, store)
    opened = await aio.open(f"{DATA}/c.json", store)
    _, ref_child = opened.children()

    with pytest.raises(NodeStateError):  # document root: already its own document
        await aio.externalize(opened, f"{DATA}/x.zarr", store)
    with pytest.raises(NodeStateError):  # already a reference
        await aio.externalize(ref_child, f"{DATA}/x.zarr", store)
    with pytest.raises(NodeStateError):  # detached
        await aio.externalize(
            _collection("d", children=[_image("m")]).find(uid("m")),
            f"{DATA}/x.zarr",
            store,
        )
    inlined = await aio.open_inlined(f"{DATA}/c.json", store)
    with pytest.raises(NodeStateError):  # inlined trees are read-only
        await aio.externalize(inlined.find(uid("img")), f"{DATA}/x.zarr", store)
    with pytest.raises(NodeStateError):  # occupied destination
        await aio.externalize(opened.find(uid("img")), f"{DATA}/image.zarr", store)
    # ... unless overwrite is passed
    updated = await aio.externalize(
        opened.find(uid("img")), f"{DATA}/image.zarr", store, overwrite=True
    )
    assert updated.children()[0].is_reference


def test_externalize_sync_on_local_store(tmp_path) -> None:
    import ngio_collections as ngc

    root = ngc.new_node(
        "collection",
        id=uid("root"),
        name="test",
        children=[
            ngc.new_node(
                "collection",
                id=uid("crop"),
                name="crop",
                children=[ngc.new_node("multiscale", id=uid("img"), name="img")],
            )
        ],
    )
    ngc.create(str(tmp_path / "c.json"), root)
    opened = ngc.open(str(tmp_path / "c.json"))
    updated = ngc.externalize(opened.find(uid("crop")), str(tmp_path / "crop.zarr"))
    assert (tmp_path / "crop.zarr" / "zarr.json").exists()
    assert updated.children()[0].is_reference
    assert ngc.open_inlined(str(tmp_path / "c.json")).find(uid("img")) is not None


async def test_open_ref_resolves_subtree_across_documents() -> None:
    store = MemoryStore()
    stub = await aio.create(f"{DATA}/image.zarr", _image("image", role="target"), store)
    await aio.create(f"{DATA}/c.json", _collection("root").add_ref(stub), store)

    # Take a reference the way a user would: from the unresolved stub on disk.
    opened = await aio.open(f"{DATA}/c.json", store)
    ref = opened.children()[0].ref()

    node = await aio.open_ref(ref, opened.document_url, store)
    assert node.id == uid("image") and node.type == "multiscale"
    assert node.attributes["role"] == "target"
    # The opened subtree is editable (cross-doc, not inlined/read-only).
    assert node.tree.mode == "editable"


async def test_open_ref_reaches_an_inner_node() -> None:
    store = MemoryStore()
    scene = _collection("scene", children=[_collection("crop", children=[_image("m")])])
    await aio.create(f"{DATA}/scene.zarr", scene, store)
    ref = ReferenceObj(
        type="collection", ref=uid("crop"), path=ZarrPath(href=f"{DATA}/scene.zarr")
    )
    crop = await aio.open_ref(ref, store=store)
    assert crop.id == uid("crop") and [n.id for n in crop.walk()] == [
        uid("crop"),
        uid("m"),
    ]


async def test_open_inlined_ref_resolves_nested_references() -> None:
    store = MemoryStore()
    # leaf -> mid -> entry chain of single-child documents
    leaf_stub = await aio.create(f"{DATA}/leaf.zarr", _image("leaf", role="deep"), store)
    mid_stub = await aio.create(f"{DATA}/mid.json", _collection("mid").add_ref(leaf_stub), store)
    await aio.create(f"{DATA}/entry.json", _collection("root").add_ref(mid_stub), store)

    opened = await aio.open(f"{DATA}/entry.json", store)
    ref = opened.children()[0].ref()

    view = await aio.open_inlined_ref(ref, opened.document_url, store)
    assert view.id == uid("mid") and view.tree.mode == "resolved"
    # The nested leaf reference was inlined too, not left as a stub.
    leaf_node = view.find(uid("leaf"))
    assert leaf_node is not None and not leaf_node.is_reference
    assert leaf_node.attributes["role"] == "deep"


async def test_open_ref_missing_id_raises_lookup_error() -> None:
    store = MemoryStore()
    await aio.create(f"{DATA}/image.zarr", _image("image"), store)
    ref = ReferenceObj(
        type="multiscale", ref=uid("absent"), path=ZarrPath(href=f"{DATA}/image.zarr")
    )
    with pytest.raises(LookupError):
        await aio.open_ref(ref, store=store)


async def test_open_ref_type_mismatch_raises_type_error() -> None:
    store = MemoryStore()
    await aio.create(f"{DATA}/image.zarr", _image("image"), store)
    ref = ReferenceObj(
        type="collection", ref=uid("image"), path=ZarrPath(href=f"{DATA}/image.zarr")
    )
    with pytest.raises(TypeError):
        await aio.open_ref(ref, store=store)
    with pytest.raises(TypeError):
        await aio.open_inlined_ref(ref, store=store)


async def test_open_ref_without_path_raises() -> None:
    with pytest.raises(NodeStateError):
        await aio.open_ref(ReferenceObj(type="multiscale", ref=uid("image")))


async def test_create_rejects_a_tree_built_with_origin_url() -> None:
    store = MemoryStore()
    node = new_node("multiscale", id=uid("img"), origin_url=f"{DATA}/image.zarr")
    with pytest.raises(NodeStateError):
        await aio.create(f"{DATA}/other.zarr", node, store)


async def test_create_refuses_existing_without_overwrite() -> None:
    store = MemoryStore()
    await aio.create(f"{DATA}/c.json", _collection("root"), store)
    with pytest.raises(NodeStateError):
        await aio.create(f"{DATA}/c.json", _collection("other"), store)
