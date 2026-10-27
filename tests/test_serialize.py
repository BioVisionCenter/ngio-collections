"""Tests for the write path: serialize a NodeTree back to documents.

Covers payload shape and key order, declaring-entry round-trip, path
relativization on nodes and inside traits / fields, the embedded-multiscale
guard, that a resolved view serializes back to its entry document, and a full
build → write → re-read round-trip through a writable in-memory store.
"""

from __future__ import annotations

import pytest

from ngio_collections.api import MemoryStore
from ngio_collections.graph import ROOT, NodeRecord, NodeTree
from ngio_collections.models import ExtensionManifestEntry, ExtensionRegistry, SchemaRef
from ngio_collections.models._paths import DocPath, ZarrPath
from ngio_collections.resolve import (
    EmbeddedMultiscaleError,
    build,
    derive_manifest,
    fetch_all,
    node_dict,
    payload,
    used_extension_types,
    write_document,
)
from tests.conftest import DATA, mk

RENDER = "https://napari.org/ngff/rendering"
WELL = {"type": "well", "row_index": 0, "column_index": 0}
NAPARI = ExtensionManifestEntry(
    id="https://napari.org/ngff/",
    version="1.0",
    schemas=[SchemaRef(type="jsonschema", url="https://napari.org/ngff/1.0.json")],
)


def _sample() -> NodeTree:
    """root → {labels (embedded collection) → img (external multiscale)}."""
    c = NodeTree.of(NodeRecord(type="collection", id=mk(0), name="root", children=()))
    c, labels = c.add_child(
        ROOT,
        NodeRecord(type="collection", id=mk(2), traits={"well": WELL}, children=()),
    )
    c, _ = c.add_child(
        labels,
        NodeRecord(
            type="multiscale",
            id=mk(1),
            name="img",
            traits={RENDER: {"type": RENDER, "contrast_limits": [0, 1]}},
            path=ZarrPath(href="./img"),
        ),
    )
    return c


def test_payload_shape_and_key_order() -> None:
    body = payload(_sample(), base_url=f"{DATA}/c.json", relativize=False)
    assert list(body)[:3] == ["version", "type", "id"]  # no manifest when empty
    assert (
        body["type"] == "collection" and body["id"] == mk(0) and body["name"] == "root"
    )
    (labels,) = body["nodes"]
    assert list(labels) == ["type", "id", "traits", "nodes"]  # name None dropped
    assert labels["traits"] == [WELL]
    (img,) = labels["nodes"]
    assert list(img) == ["type", "id", "name", "path", "traits"]
    assert img["path"] == {"type": "zarr", "format": "relative", "href": "./img"}
    assert "nodes" not in img


def test_payload_carries_the_manifest_when_given() -> None:
    manifest = [{"id": "https://napari.org/ngff/", "version": "1.0", "schemas": []}]
    body = payload(_sample(), base_url=f"{DATA}/c.json", extension_manifest=manifest)
    assert list(body)[:2] == ["version", "extension_manifest"]
    assert body["extension_manifest"] == manifest


def test_fields_are_emitted_on_the_node() -> None:
    fields = {"coordinate_systems": [], "scales": []}
    c = NodeTree.of(NodeRecord(type="multiscale", id=mk(1), fields=fields))
    body = payload(c, base_url=f"{DATA}/img/zarr.json")
    assert list(body) == ["version", "type", "id", "coordinate_systems", "scales"]


def test_relativize_rewrites_node_path_and_embedded_path_objects() -> None:
    c = NodeTree.of(NodeRecord(type="collection", id=mk(0), children=()))
    c, _ = c.add_child(
        ROOT,
        NodeRecord(
            type="multiscale",
            id=mk(1),
            path=DocPath(type="zarr", format="absolute", href="/data/image.zarr"),
            traits={
                "labels": {
                    "type": "labels",
                    "source": [
                        {
                            "type": "multiscale",
                            "ref": mk(3),
                            "path": {
                                "type": "zarr",
                                "format": "absolute",
                                "href": "/data/raw.zarr",
                            },
                        }
                    ],
                }
            },
        ),
    )
    (stub,) = payload(c, base_url=f"{DATA}/c.json", relativize=True)["nodes"]
    assert stub["path"] == {
        "type": "zarr",
        "format": "relative",
        "href": "./image.zarr",
    }
    assert stub["traits"][0]["source"][0]["path"]["href"] == "./raw.zarr"
    # http hrefs stay verbatim
    remote = NodeTree.of(
        NodeRecord(
            type="multiscale",
            id=mk(1),
            fields={
                "scales": [
                    {
                        "type": "scale",
                        "id": mk(9),
                        "path": {
                            "type": "zarr",
                            "format": "http",
                            "href": "https://h.org/a/0",
                        },
                    }
                ]
            },
        )
    )
    body = payload(remote, base_url=f"{DATA}/img/zarr.json", relativize=True)
    assert body["scales"][0]["path"]["href"] == "https://h.org/a/0"


def test_embedded_multiscale_is_refused_when_strict() -> None:
    c = NodeTree.of(NodeRecord(type="collection", id=mk(0), children=()))
    c, _ = c.add_child(ROOT, NodeRecord(type="multiscale", id=mk(1), fields={}))
    with pytest.raises(EmbeddedMultiscaleError):
        payload(c, base_url=f"{DATA}/c.json")
    lenient = node_dict(
        c, ROOT, base_url=f"{DATA}/c.json", relativize=False, strict=False
    )
    assert lenient["nodes"][0]["type"] == "multiscale"
    # a multiscale as the document root is fine
    payload(
        NodeTree.of(NodeRecord(type="multiscale", id=mk(1))),
        base_url=f"{DATA}/i/zarr.json",
    )


async def test_resolved_view_serializes_back_to_the_entry_document(
    revision_store,
) -> None:
    url = f"{DATA}/collection/zarr.json"
    original = (await revision_store.get(url))["attributes"]["ome"]
    view = build(url, await fetch_all(url, revision_store), inline=True)
    body = payload(view.tree if hasattr(view, "tree") else view, base_url=url)
    assert body["nodes"] == original["nodes"]
    assert body["traits"] == original["traits"]


# --------------------------------------------------------------------------- #
# Round-trip through a store, manifests
# --------------------------------------------------------------------------- #


async def test_write_then_read_round_trips() -> None:
    original = _sample()
    store = MemoryStore()
    url = await write_document(store, f"{DATA}/c.json", original)
    reread = build(url, await fetch_all(url, store, depth=0), inline=False)
    assert [reread.record(n).id for n in reread.walk()] == [
        original.record(n).id for n in original.walk()
    ]
    img = reread.record(reread.find(mk(1))[0])
    assert img.is_external and img.traits[RENDER]["contrast_limits"] == [0, 1]


async def test_unedited_write_is_identical_on_resave() -> None:
    store = MemoryStore()
    url = await write_document(store, f"{DATA}/c.json", _sample())
    first = await store.get(url)
    reread = build(url, await fetch_all(url, store, depth=0), inline=False)
    await write_document(store, url, reread, existing=first, overwrite=True)
    assert await store.get(url) == first


def test_used_extension_types_stop_at_document_boundaries() -> None:
    c = _sample()  # RENDER is on the external entry; counted (the entry is ours)
    assert used_extension_types(c) == (RENDER,)
    registry = (
        ExtensionRegistry(
            [{"id": "https://napari.org/ngff/", "version": "1.0"}]  # type: ignore[list-item]
        )
        if False
        else ExtensionRegistry()
    )
    registry.register(NAPARI)
    assert derive_manifest(c, registry=registry) == [NAPARI.to_dict()]
    # an unknown URI is left undeclared, never a failure
    assert derive_manifest(c) == []


def test_uri_path_types_are_used_types_and_relativized() -> None:
    ext = "https://ext.example/fractal/"
    table, csv = ext + "table", ext + "csv"
    c = NodeTree.of(NodeRecord(type="collection", id=mk(0), children=()))
    c, _ = c.add_child(
        ROOT,
        NodeRecord(
            type=table,
            id=mk(1),
            path=DocPath(type=csv, format="absolute", href=f"{DATA}/tables/t.csv"),
            fields={
                "sidecar": {"type": csv, "format": "absolute", "href": f"{DATA}/s.csv"}
            },
        ),
    )
    assert used_extension_types(c) == (table, csv)
    entry = ExtensionManifestEntry(
        id=ext,
        version="0.1",
        schemas=[SchemaRef(type="jsonschema", url=ext + "s.json")],
    )
    assert derive_manifest(c, registry=ExtensionRegistry([entry])) == [entry.to_dict()]
    # the node path and the path object inside a field both relativize on write
    (node,) = payload(c, base_url=f"{DATA}/c.json", relativize=True)["nodes"]
    assert node["path"] == {"type": csv, "format": "relative", "href": "./tables/t.csv"}
    assert node["sidecar"] == {"type": csv, "format": "relative", "href": "./s.csv"}


async def test_write_derives_and_preserves_manifest_entries() -> None:
    store = MemoryStore()
    registry = ExtensionRegistry([NAPARI])
    url = await write_document(store, f"{DATA}/c.json", _sample(), registry=registry)
    written = (await store.get(url))["ome"]
    assert written["extension_manifest"][0]["id"] == "https://napari.org/ngff/"
    # re-saving without the registry keeps the entry the document already declared
    reread = build(url, await fetch_all(url, store, depth=0), inline=False)
    await write_document(
        store, url, reread, existing=await store.get(url), overwrite=True
    )
    assert (await store.get(url))["ome"]["extension_manifest"] == written[
        "extension_manifest"
    ]
