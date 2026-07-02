"""End-to-end tests for the async public API over a writable in-memory store.

Exercises the full create → open → edit → save and compose-via-reference flows,
plus inlining and delete, through the real `open`/`create`/`save`/`save_inlined`/
`delete` verbs.
"""

from __future__ import annotations

import ngio_collections.api._api as aio
from ngio_collections.api import MemoryStore, new_node
from ngio_collections.models._paths import ZarrPath
from ngio_collections.models._references import ReferenceObj
from ngio_collections.models.attributes import WellAttribute

DATA = "/data"


async def test_create_open_edit_save_roundtrip() -> None:
    store = MemoryStore()
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
    store = MemoryStore()
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
    store = MemoryStore()
    image = new_node("multiscale", id="image", name="Image")
    created_stub = await aio.create(f"{DATA}/image.zarr", image, store)

    # a stub minted from the opened node is the same shape create() returned
    opened = await aio.open(f"{DATA}/image.zarr", store)
    stub = opened.ref_stub()
    assert stub.is_reference and stub.is_detached
    assert stub.ref_path == created_stub.ref_path == f"{DATA}/image.zarr"
    assert stub.id == created_stub.id == "image"
    assert stub.record.ref.id == "image"
    assert stub.type == "multiscale" and stub.name == "Image"

    # and it composes into a parent exactly like create()'s stub does
    parent = new_node("collection", id="root").add_ref(stub)
    await aio.create(f"{DATA}/c.json", parent, store)
    inlined = await aio.open_inlined(f"{DATA}/c.json", store)
    image_node = inlined.find("image")
    assert image_node is not None and not image_node.is_reference


async def test_minted_stubs_carry_id_and_are_findable_after_reopen() -> None:
    store = MemoryStore()
    image = new_node("multiscale", id="image", name="Image")
    stub = await aio.create(f"{DATA}/image.zarr", image, store)
    assert stub.id == "image" and stub.record.ref.id == "image"

    parent = new_node("collection", id="root").add_ref(stub)
    assert parent.find("image") is not None  # findable in-memory
    await aio.create(f"{DATA}/c.json", parent, store)

    reopened = await aio.open(f"{DATA}/c.json", store)
    found = reopened.find("image")
    assert found is not None and found.is_reference

    # remove() works uniformly on a stub located by id
    pruned = found.remove()
    assert pruned.find("image") is None


async def test_id_less_doc_root_stub_opens_and_resolves() -> None:
    store = MemoryStore()
    image = new_node("multiscale", name="anonymous", attributes={"role": "target"})
    stub = await aio.create(f"{DATA}/image.zarr", image, store)
    assert stub.id is None and stub.record.ref.id is None

    parent = new_node("collection", id="root").add_ref(stub)
    await aio.create(f"{DATA}/c.json", parent, store)

    (child,) = (await aio.open(f"{DATA}/c.json", store)).children()
    assert child.is_reference and child.id is None

    (resolved,) = (await aio.open_inlined(f"{DATA}/c.json", store)).children()
    assert not resolved.is_reference
    assert resolved.attributes["role"] == "target"


async def test_children_literal_mixes_stub_and_embedded() -> None:
    store = MemoryStore()
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
    store = MemoryStore()
    image = new_node("multiscale", id="image", attributes={"role": "x"})
    stub = await aio.create(f"{DATA}/image.zarr", image, store)
    parent = new_node("collection", id="root").add_ref(stub)
    await aio.create(f"{DATA}/c.json", parent, store)

    view = await aio.open_inlined(f"{DATA}/c.json", store)
    await aio.save_inlined(view, f"{DATA}/flat.json", store)

    flat = await aio.open(f"{DATA}/flat.json", store)
    assert flat.find("image") is not None  # embedded inline now
    assert not flat.find("image").is_reference


async def test_subtree_of_inlined_node_is_fully_detached() -> None:
    store = MemoryStore()
    image = new_node("multiscale", id="image", attributes={"role": "x"})
    stub = await aio.create(f"{DATA}/image.zarr", image, store)
    parent = new_node("collection", id="root").add_ref(stub.set_attrs({"role": "raw"}))
    await aio.create(f"{DATA}/c.json", parent, store)

    view = await aio.open_inlined(f"{DATA}/c.json", store)
    assert view.find("image").record.edge is not None  # boundary provenance kept
    sub = view.find("image").subtree()
    assert sub.is_detached and sub.record.edge is None  # ...but not extracted


async def test_delete_removes_document() -> None:
    store = MemoryStore()
    root = new_node("collection", id="root").add(new_node("multiscale", id="img"))
    await aio.create(f"{DATA}/c.json", root, store)
    opened = await aio.open(f"{DATA}/c.json", store)
    affected = await aio.delete(opened, store)
    assert affected == [f"{DATA}/c.json"]
    assert f"{DATA}/c.json" not in store


async def test_externalize_splits_node_into_own_document() -> None:
    store = MemoryStore()
    root = new_node(
        "collection",
        id="root",
        children=[
            new_node(
                "multiscale",
                id="img",
                attributes={"role": "raw"},
                children=[new_node("singlescale", id="0")],
            ),
            new_node("multiscale", id="table"),
        ],
    )
    await aio.create(f"{DATA}/c.json", root, store)
    before = await aio.open_inlined(f"{DATA}/c.json", store)

    opened = await aio.open(f"{DATA}/c.json", store)
    updated = await aio.externalize(opened.find("img"), f"{DATA}/img.zarr", store)

    # returned root: a stub in place of the node, same sibling position
    children = updated.children()
    assert [c.id for c in children] == ["img", "table"]
    assert children[0].is_reference and children[0].ref_path == f"{DATA}/img.zarr"
    assert updated.find("0") is None

    # the new document holds the subtree
    img_doc = await aio.open(f"{DATA}/img.zarr", store)
    assert [n.id for n in img_doc.walk()] == ["img", "0"]
    assert img_doc.attributes["role"] == "raw"

    # the home document was rewritten; the inlined view is unchanged
    reopened = await aio.open(f"{DATA}/c.json", store)
    assert reopened.find("img").is_reference
    after = await aio.open_inlined(f"{DATA}/c.json", store)
    assert [(n.id, dict(n.attributes)) for n in after.walk()] == [
        (n.id, dict(n.attributes)) for n in before.walk()
    ]


async def test_externalize_rejects_invalid_targets() -> None:
    import pytest

    from ngio_collections.models._config import NodeStateError

    store = MemoryStore()
    image = new_node("multiscale", id="image")
    stub = await aio.create(f"{DATA}/image.zarr", image, store)
    root = new_node(
        "collection", id="root", children=[new_node("multiscale", id="img")]
    ).add_ref(stub)
    await aio.create(f"{DATA}/c.json", root, store)
    opened = await aio.open(f"{DATA}/c.json", store)

    with pytest.raises(NodeStateError):  # document root: already its own document
        await aio.externalize(opened, f"{DATA}/x.zarr", store)
    with pytest.raises(NodeStateError):  # already a reference
        await aio.externalize(opened.find("image"), f"{DATA}/x.zarr", store)
    with pytest.raises(NodeStateError):  # detached
        await aio.externalize(
            new_node(
                "collection", id="d", children=[new_node("multiscale", id="m")]
            ).find("m"),
            f"{DATA}/x.zarr",
            store,
        )
    inlined = await aio.open_inlined(f"{DATA}/c.json", store)
    with pytest.raises(NodeStateError):  # inlined trees are read-only
        await aio.externalize(inlined.find("img"), f"{DATA}/x.zarr", store)
    with pytest.raises(NodeStateError):  # occupied destination
        await aio.externalize(opened.find("img"), f"{DATA}/image.zarr", store)
    # ... unless overwrite is passed
    updated = await aio.externalize(
        opened.find("img"), f"{DATA}/image.zarr", store, overwrite=True
    )
    assert updated.find("img").is_reference


def test_externalize_sync_on_local_store(tmp_path) -> None:
    import ngio_collections as ngc

    root = ngc.new_node(
        "collection",
        id="root",
        children=[
            ngc.new_node(
                "multiscale", id="img", children=[ngc.new_node("singlescale", id="0")]
            )
        ],
    )
    ngc.create(str(tmp_path / "c.json"), root)
    opened = ngc.open(str(tmp_path / "c.json"))
    updated = ngc.externalize(opened.find("img"), str(tmp_path / "img.zarr"))
    assert (tmp_path / "img.zarr" / "zarr.json").exists()
    assert updated.find("img").is_reference
    assert ngc.open_inlined(str(tmp_path / "c.json")).find("0") is not None


async def test_open_ref_resolves_subtree_across_documents() -> None:
    store = MemoryStore()
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
    store = MemoryStore()
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

    store = MemoryStore()
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


async def test_create_rejects_a_tree_built_with_origin_url() -> None:
    import pytest

    from ngio_collections.models._config import NodeStateError

    store = MemoryStore()
    node = new_node("multiscale", id="img", origin_url=f"{DATA}/image.zarr")
    with pytest.raises(NodeStateError):
        await aio.create(f"{DATA}/other.zarr", node, store)


async def test_create_refuses_existing_without_overwrite() -> None:
    import pytest

    from ngio_collections.models._config import NodeStateError

    store = MemoryStore()
    root = new_node("collection", id="root")
    await aio.create(f"{DATA}/c.json", root, store)
    with pytest.raises(NodeStateError):
        await aio.create(f"{DATA}/c.json", new_node("collection", id="other"), store)
