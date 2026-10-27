"""End-to-end tests for the async public API over a writable in-memory store.

Exercises create → link → open → resolve → edit → save, typed references across
documents, externalize and delete, through the real verbs.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

import ngio_collections as ngc
import ngio_collections.api._api as aio
from ngio_collections.api import MemoryStore
from ngio_collections.models import (
    ExtensionManifestEntry,
    ExtensionRegistry,
    SchemaRef,
)
from ngio_collections.models._errors import NodeStateError
from ngio_collections.resolve import EmbeddedMultiscaleError, IdMismatchError
from tests._builders import collection, multiscale
from tests.conftest import DATA, mk, requires_pydantic

RENDER = "https://napari.org/ngff/rendering"


NAPARI_ENTRY = ExtensionManifestEntry(
    id="https://napari.org/ngff/",
    version="1.0",
    schemas=[SchemaRef(type="jsonschema", url="https://napari.org/ngff/1.0.json")],
)
NAPARI = ExtensionRegistry([NAPARI_ENTRY])


async def _image_and_collection(store: MemoryStore) -> tuple[ngc.Node, ngc.Node]:
    """Create `/data/raw` (multiscale) and `/data/zarr.json` linking it."""
    stub = await aio.create(f"{DATA}/raw", multiscale(2, name="raw"), store)
    stub = stub.set_trait({"type": RENDER, "contrast_limits": [0, 1500]})
    root = collection(1, name="exp").add_external(stub)
    await aio.create(f"{DATA}/zarr.json", root, store, registry=NAPARI)
    return stub, root


@requires_pydantic  # `.scales` and ALL_VALIDATORS read through the typed models
async def test_create_link_open_resolve_roundtrip() -> None:
    store = MemoryStore()
    stub, _ = await _image_and_collection(store)
    assert stub.is_external and stub.id == mk(2) and stub.ref_path == f"{DATA}/raw"

    image = await aio.open(f"{DATA}/raw", store)
    assert isinstance(image, ngc.MultiscaleNode) and len(image.scales) == 2
    assert image.document_url == f"{DATA}/raw/zarr.json"

    opened = await aio.open(f"{DATA}/zarr.json", store)
    (entry,) = opened.children()
    assert entry.is_external and entry.id == mk(2)
    assert entry.path is not None and entry.path.href == "./raw"  # relativized on write

    view = await aio.open_resolved(f"{DATA}/zarr.json", store)
    raw = view.find(mk(2))
    assert (
        raw is not None and not raw.is_external and isinstance(raw, ngc.MultiscaleNode)
    )
    assert raw.traits[RENDER]["contrast_limits"] == [0, 1500]  # the entry's trait
    assert len(raw.scales) == 2 and raw.record.edge is not None
    assert view.validate(ngc.ALL_VALIDATORS) == []


async def test_entry_trait_overrides_target_trait_and_save_keeps_the_split() -> None:
    store = MemoryStore()
    image = multiscale(
        2, traits=[{"type": RENDER, "contrast_limits": [9, 9], "gamma": 2}]
    )
    stub = (await aio.create(f"{DATA}/raw", image, store)).set_trait(
        {"type": RENDER, "contrast_limits": [0, 1]}
    )
    await aio.create(f"{DATA}/zarr.json", collection(1).add_external(stub), store)

    view = await aio.open_resolved(f"{DATA}/zarr.json", store)
    assert view.find(mk(2)).traits[RENDER] == {
        "type": RENDER,
        "contrast_limits": [0, 1],
    }
    with pytest.raises(NodeStateError):
        await aio.save(view, store)  # resolved views are read-only

    # edit the entry in the collection; the image document is untouched
    opened = await aio.open(f"{DATA}/zarr.json", store)
    await aio.save(
        opened.find(mk(2)).set_trait({"type": RENDER, "contrast_limits": [5, 6]}), store
    )
    assert (await aio.open(f"{DATA}/raw", store)).traits[RENDER]["gamma"] == 2
    assert (await aio.open_resolved(f"{DATA}/zarr.json", store)).find(mk(2)).traits[
        RENDER
    ] == {
        "type": RENDER,
        "contrast_limits": [5, 6],
    }


async def test_stub_matches_create_stub_and_is_findable_after_reopen() -> None:
    store = MemoryStore()
    created = await aio.create(f"{DATA}/image.zarr", multiscale(2, name="Image"), store)
    stub = (await aio.open(f"{DATA}/image.zarr", store)).stub()
    assert stub.is_external and stub.is_detached
    assert stub.ref_path == created.ref_path == f"{DATA}/image.zarr"
    assert stub.id == created.id == mk(2) and stub.name == "Image"

    parent = collection(1).add_external(stub)
    assert parent.find(mk(2)) is not None
    await aio.create(f"{DATA}/c.json", parent, store)
    reopened = await aio.open(f"{DATA}/c.json", store)
    found = reopened.find(mk(2))
    assert found is not None and found.is_external
    assert found.remove().find(mk(2)) is None


async def test_entry_and_target_must_share_the_uuid() -> None:
    store = MemoryStore()
    await aio.create(f"{DATA}/image.zarr", multiscale(2), store)
    wrong = ngc.new_node("multiscale", id=mk(7), path=ngc.ZarrPath(href="./image.zarr"))
    await aio.create(f"{DATA}/c.json", collection(1).add_external(wrong), store)
    view = await aio.open_resolved(f"{DATA}/c.json", store)
    assert view.find(mk(7)).is_external  # left unresolved
    assert [e.validator for e in view.validate(ngc.CORE_VALIDATORS)] == [
        "external_unresolved"
    ]
    with pytest.raises(IdMismatchError):
        await aio.open_resolved(f"{DATA}/c.json", store, on_error="raise")


@requires_pydantic  # validators / `.scales` read through the typed models
async def test_manifest_is_derived_from_the_registry_and_exposed() -> None:
    store = MemoryStore()
    stub = (await aio.create(f"{DATA}/raw", multiscale(2), store)).set_trait(
        {"type": RENDER, "contrast_limits": [0, 1]}
    )
    await aio.create(
        f"{DATA}/zarr.json", collection(1).add_external(stub), store, registry=NAPARI
    )
    doc = (await store.get(f"{DATA}/zarr.json"))["attributes"]["ome"]
    assert [e["id"] for e in doc["extension_manifest"]] == ["https://napari.org/ngff/"]
    assert (
        "extension_manifest"
        not in (await store.get(f"{DATA}/raw/zarr.json"))["attributes"]["ome"]
    )
    opened = await aio.open(f"{DATA}/zarr.json", store)
    assert opened.extension_manifest[0]["id"] == "https://napari.org/ngff/"
    assert opened.validate(ngc.CORE_VALIDATORS) == []
    view = await aio.open_resolved(f"{DATA}/zarr.json", store)
    assert view.validate(ngc.CORE_VALIDATORS) == []


async def test_nested_collections_embed_or_link() -> None:
    store = MemoryStore()
    stub = await aio.create(f"{DATA}/raw", multiscale(2), store)
    embedded = collection(3, stub, name="embedded")
    await aio.create(f"{DATA}/scene.json", collection(1).add(embedded), store)
    view = await aio.open_resolved(f"{DATA}/scene.json", store)
    assert [n.id for n in view.walk()] == [mk(1), mk(3), mk(2)]
    assert not view.find(mk(3)).is_external and not view.find(mk(2)).is_external


async def test_subtree_of_resolved_node_is_fully_detached() -> None:
    store = MemoryStore()
    await _image_and_collection(store)
    view = await aio.open_resolved(f"{DATA}/zarr.json", store)
    assert view.find(mk(2)).record.edge is not None
    sub = view.find(mk(2)).subtree()
    assert sub.is_detached and sub.record.edge is None and sub.tree.mode == "editable"


async def test_delete_and_cascade() -> None:
    store = MemoryStore()
    await _image_and_collection(store)
    opened = await aio.open(f"{DATA}/zarr.json", store)
    affected = await aio.delete(opened.find(mk(2)), store)  # the entry only
    assert affected == [f"{DATA}/zarr.json"]
    assert (await aio.open(f"{DATA}/zarr.json", store)).children() == ()
    assert await store.contains(f"{DATA}/raw/zarr.json")

    await aio.save(opened, store)  # restore the entry
    affected = await aio.delete(
        (await aio.open(f"{DATA}/zarr.json", store)).find(mk(2)), store, cascade=True
    )
    assert affected == [f"{DATA}/raw/zarr.json", f"{DATA}/zarr.json"]
    assert not await store.contains(f"{DATA}/raw/zarr.json")

    root = await aio.open(f"{DATA}/zarr.json", store)
    assert await aio.delete(root, store) == [f"{DATA}/zarr.json"]
    assert not await store.contains(f"{DATA}/zarr.json")


async def test_externalize_splits_a_collection_into_its_own_document() -> None:
    store = MemoryStore()
    stub = await aio.create(f"{DATA}/raw", multiscale(2), store)
    root = collection(1, collection(3, stub, name="labels"), collection(4))
    await aio.create(f"{DATA}/c.json", root, store)
    before = await aio.open_resolved(f"{DATA}/c.json", store)

    opened = await aio.open(f"{DATA}/c.json", store)
    updated = await aio.externalize(opened.find(mk(3)), f"{DATA}/labels.json", store)
    children = updated.children()
    assert [c.id for c in children] == [mk(3), mk(4)]
    assert children[0].is_external and children[0].ref_path == f"{DATA}/labels.json"
    assert updated.find(mk(2)) is None

    labels_doc = await aio.open(f"{DATA}/labels.json", store)
    assert [n.id for n in labels_doc.walk()] == [mk(3), mk(2)]
    after = await aio.open_resolved(f"{DATA}/c.json", store)
    assert [n.id for n in after.walk()] == [n.id for n in before.walk()]


async def test_externalize_rejects_invalid_targets() -> None:
    store = MemoryStore()
    stub = await aio.create(f"{DATA}/image.zarr", multiscale(2), store)
    root = collection(1, collection(3), stub)
    await aio.create(f"{DATA}/c.json", root, store)
    opened = await aio.open(f"{DATA}/c.json", store)
    with pytest.raises(NodeStateError):  # document root
        await aio.externalize(opened, f"{DATA}/x.json", store)
    with pytest.raises(NodeStateError):  # already external
        await aio.externalize(opened.find(mk(2)), f"{DATA}/x.json", store)
    with pytest.raises(NodeStateError):  # detached
        await aio.externalize(
            collection(1, collection(3)).find(mk(3)), f"{DATA}/x.json", store
        )
    view = await aio.open_resolved(f"{DATA}/c.json", store)
    with pytest.raises(NodeStateError):  # resolved views are read-only
        await aio.externalize(view.find(mk(3)), f"{DATA}/x.json", store)
    with pytest.raises(NodeStateError):  # occupied destination
        await aio.externalize(opened.find(mk(3)), f"{DATA}/image.zarr", store)
    updated = await aio.externalize(
        opened.find(mk(3)), f"{DATA}/image.zarr", store, overwrite=True
    )
    assert updated.find(mk(3)).is_external


@requires_pydantic  # validators / `.scales` read through the typed models
def test_sync_api_on_local_store(tmp_path) -> None:
    image_url = str(tmp_path / "raw")
    stub = ngc.create(image_url, multiscale(2), None)
    ngc.create(
        str(tmp_path / "c.json"), collection(1, collection(3, name="inner"), stub)
    )
    assert (tmp_path / "raw" / "zarr.json").exists()
    opened = ngc.open(str(tmp_path / "c.json"))
    updated = ngc.externalize(opened.find(mk(3)), str(tmp_path / "inner.json"))
    assert updated.find(mk(3)).is_external and (tmp_path / "inner.json").exists()
    view = ngc.open_resolved(str(tmp_path / "c.json"))
    assert not view.find(mk(2)).is_external and view.validate(ngc.ALL_VALIDATORS) == []


@requires_pydantic  # `.scales`
async def test_open_ref_follows_typed_references() -> None:
    store = MemoryStore()
    await _image_and_collection(store)
    opened = await aio.open(f"{DATA}/zarr.json", store)
    (entry,) = opened.children()
    ref = ngc.ReferenceObj(type="multiscale", ref=entry.id, path=entry.path)
    node = await aio.open_ref(ref, opened.document_url, store)
    assert node.id == mk(2) and node.tree.mode == "editable" and len(node.scales) == 2
    with pytest.raises(LookupError):  # type mismatch
        await aio.open_ref(
            ngc.ReferenceObj(type="collection", ref=entry.id, path=entry.path),
            opened.document_url,
            store,
        )
    with pytest.raises(LookupError):  # absent
        await aio.open_ref(
            ngc.ReferenceObj(type="multiscale", ref=mk(9), path=entry.path),
            opened.document_url,
            store,
        )
    with pytest.raises(TypeError):  # a nested declaration, not a node
        await aio.open_ref(
            ngc.ReferenceObj(type="scale", ref=node.scales[0].id, path=entry.path),
            opened.document_url,
            store,
        )
    with pytest.raises(NodeStateError):  # no path
        await aio.open_ref(ngc.ReferenceObj(type="multiscale", ref=mk(2)))


@requires_pydantic  # `.scales`
async def test_resolve_ref_is_local_and_pure() -> None:
    store = MemoryStore()
    await _image_and_collection(store)
    image = await aio.open(f"{DATA}/raw", store)
    scale = image.scales[0]
    declaration = aio.resolve_ref(image, ngc.ReferenceObj(type="scale", ref=scale.id))
    assert declaration["path"]["href"] == "./s0"
    system = aio.resolve_ref(image, scale.coordinate_transformations[0].output)
    assert system["type"] == "coordinate_system"
    with pytest.raises(LookupError):
        aio.resolve_ref(image, ngc.ReferenceObj(type="coordinate_system", ref=scale.id))
    view = await aio.open_resolved(f"{DATA}/zarr.json", store)
    assert aio.resolve_ref(view, view.find(mk(2)).ref_local()).id == mk(2)
    with pytest.raises(NodeStateError):
        aio.resolve_ref(view, view.find(mk(2)).ref())


async def test_open_resolved_ref_resolves_nested_documents() -> None:
    store = MemoryStore()
    leaf = await aio.create(f"{DATA}/leaf.zarr", multiscale(5), store)
    mid = await aio.create(f"{DATA}/mid.json", collection(6).add_external(leaf), store)
    await aio.create(f"{DATA}/entry.json", collection(1).add_external(mid), store)
    opened = await aio.open(f"{DATA}/entry.json", store)
    (entry,) = opened.children()
    view = await aio.open_resolved_ref(
        replace(entry.ref_local(), path=entry.path),
        opened.document_url,
        store,
    )
    assert view.id == mk(6) and view.tree.mode == "resolved"
    assert not view.find(mk(5)).is_external


async def test_create_guards() -> None:
    store = MemoryStore()
    backed = ngc.new_collection(id=mk(1), name="x")
    backed = ngc.new_node("collection", id=mk(1), origin_url=f"{DATA}/x.json")
    with pytest.raises(NodeStateError):
        await aio.create(f"{DATA}/other.json", backed, store)
    await aio.create(f"{DATA}/c.json", collection(1), store)
    with pytest.raises(NodeStateError):
        await aio.create(f"{DATA}/c.json", collection(2), store)
    stub = await aio.create(f"{DATA}/raw", multiscale(2), store)
    embedded = collection(3).add_external(stub).find(mk(2)).set_path(None)
    with pytest.raises(EmbeddedMultiscaleError):
        await aio.create(f"{DATA}/bad.json", embedded, store)


@requires_pydantic  # validators / `.scales` read through the typed models
async def test_routed_store_resolves_remote_nodes() -> None:
    local, remote = MemoryStore(), MemoryStore()
    await aio.create("https://h.org/ref.zarr", multiscale(2), remote)
    entry = ngc.new_node(
        "multiscale",
        id=mk(2),
        name="published",
        path=ngc.DocPath.for_url("https://h.org/ref.zarr"),
    )
    await aio.create(f"{DATA}/c.json", collection(1).add_external(entry), local)
    assert (await local.get(f"{DATA}/c.json"))["ome"]["nodes"][0]["path"][
        "format"
    ] == "http"
    routed = ngc.RoutedStore(local=local, http=remote)
    view = await aio.open_resolved(f"{DATA}/c.json", routed)
    assert not view.find(mk(2)).is_external and view.validate(ngc.CORE_VALIDATORS) == []
    strict = await aio.open_resolved(f"{DATA}/c.json", routed, formats=ngc.CORE_FORMATS)
    assert strict.find(mk(2)).is_external
    with pytest.raises(ngc.StoreReadOnlyError):
        await aio.create("https://h.org/new.zarr", multiscale(3), routed)
