"""Tests for the L1 write path: serialize a NodeTree back to documents.

Covers payload shape, reference round-trip, path relativization, and a full
build → write → re-read → build round-trip through a writable in-memory store.
"""

from __future__ import annotations

from conftest import uid

from ngio_collections.graph import ROOT, NodeTree, NodeRecord, Reference
from ngio_collections.models._paths import ZarrPath
from ngio_collections.resolve import (
    Document,
    build,
    fetch_all,
    payload,
    write_document,
)

DATA = "/data"


class _MemoryStore:
    """A minimal writable in-memory store (url -> dict)."""

    def __init__(self) -> None:
        self.files: dict[str, dict] = {}

    async def get(self, url: str) -> dict:
        """Return the document at `url`, raising FileNotFoundError if absent."""
        try:
            return self.files[url]
        except KeyError as exc:
            raise FileNotFoundError(url) from exc

    async def put(self, url: str, data: dict, *, overwrite: bool = False) -> None:
        """Store `data` at `url`."""
        self.files[url] = data

    async def delete(self, url: str) -> None:
        """Delete `url` if present."""
        self.files.pop(url, None)


# --------------------------------------------------------------------------- #
# payload / node_dict shape
# --------------------------------------------------------------------------- #

SCALES = [{"id": uid("s0"), "path": {"type": "zarr", "format": "relative", "href": "./s0"}}]


def _root() -> NodeTree:
    return NodeTree.of(
        NodeRecord(type="collection", id=uid("root"), name="test", children=())
    )


def _sample_collection() -> NodeTree:
    c = _root()
    c, _ = c.add_child(
        ROOT,
        NodeRecord(
            type="multiscale",
            id=uid("img"),
            attributes={"traits": [], "scales": SCALES},
        ),
    )
    c, _ = c.add_child(
        ROOT, NodeRecord(type="collection", id=uid("sub"), name="sub", children=())
    )
    return c


def test_payload_rebuilds_nesting_and_splats_body_in_order() -> None:
    body = payload(_sample_collection(), base_url=f"{DATA}/c.json", relativize=False)
    assert body["version"]  # envelope stamped
    assert list(body) == ["version", "type", "id", "name", "nodes"]
    img, sub = body["nodes"]
    assert list(img) == ["type", "id", "traits", "scales"]  # no name, no nodes
    assert img["id"] == uid("img") and img["scales"] == SCALES
    assert "attributes" not in img
    assert sub == {"type": "collection", "id": uid("sub"), "name": "sub", "nodes": []}


def test_reference_record_serializes_as_type_ref_path() -> None:
    c = _root()
    c, _ = c.add_child(
        ROOT,
        NodeRecord(
            type="multiscale",
            ref=Reference(ref=uid("image"), path=ZarrPath(href="../image.zarr")),
        ),
    )
    body = payload(c, base_url=f"{DATA}/c.json", relativize=False)
    (stub,) = body["nodes"]
    assert stub == {
        "type": "multiscale",
        "ref": uid("image"),
        "path": {"type": "zarr", "format": "relative", "href": "../image.zarr"},
    }


def test_relativize_rewrites_absolute_href_and_format() -> None:
    c = _root()
    c, _ = c.add_child(
        ROOT,
        NodeRecord(
            type="multiscale",
            ref=Reference(ref=uid("image"), path=ZarrPath(href="/data/image.zarr")),
        ),
    )
    body = payload(c, base_url=f"{DATA}/c.json", relativize=True)
    (stub,) = body["nodes"]
    assert stub["path"] == {"type": "zarr", "format": "relative", "href": "./image.zarr"}


def test_relativize_rewrites_docpaths_inside_the_body() -> None:
    c = _root()
    c, _ = c.add_child(
        ROOT,
        NodeRecord(
            type="multiscale",
            id=uid("labels"),
            attributes={
                "labels": {
                    "source": [
                        {
                            "type": "multiscale",
                            "ref": uid("image"),
                            "path": {
                                "type": "zarr",
                                "format": "absolute",
                                "href": "/data/image.zarr",
                            },
                        }
                    ]
                },
                "scales": [{"id": uid("s0"), "path": "./0"}],  # plain string: kept
            },
        ),
    )
    body = payload(c, base_url=f"{DATA}/c.json", relativize=True)
    (node,) = body["nodes"]
    assert node["labels"]["source"][0]["path"] == {
        "type": "zarr",
        "format": "relative",
        "href": "./image.zarr",
    }
    assert node["scales"][0]["path"] == "./0"


# --------------------------------------------------------------------------- #
# Round-trip through a store
# --------------------------------------------------------------------------- #


async def test_write_then_read_round_trips() -> None:
    original = _sample_collection()
    store = _MemoryStore()
    url = await write_document(store, f"{DATA}/c.json", original)

    reread = build(url, await fetch_all(url, store), inline=False)
    assert [reread.record(n).id for n in reread.walk()] == [
        original.record(n).id for n in original.walk()
    ]
    assert [reread.record(n).type for n in reread.walk()] == [
        original.record(n).type for n in original.walk()
    ]
    img = reread.record(reread.find(uid("img"))[0])
    assert img.is_leaf and dict(img.attributes) == {"traits": [], "scales": SCALES}


async def test_unedited_write_is_byte_identical_on_resave() -> None:
    store = _MemoryStore()
    url = await write_document(store, f"{DATA}/c.json", _sample_collection())
    first = store.files[url]
    reread = build(url, await fetch_all(url, store), inline=False)
    await write_document(store, url, reread, existing=first, overwrite=True)
    assert store.files[url] == first


async def test_wire_document_with_references_re_serializes_identically() -> None:
    ome = {
        "version": "0.x",
        "type": "collection",
        "id": uid("root"),
        "name": "root",
        "traits": [],
        "nodes": [
            {
                "type": "collection",
                "ref": uid("crop"),
                "path": {"type": "zarr", "format": "relative", "href": "./scene"},
            },
            {"type": "multiscale", "ref": uid("local")},
        ],
    }
    store = _MemoryStore()
    url = f"{DATA}/c.json"
    store.files[url] = {"ome": ome, "sibling": 1}
    tree = build(url, await fetch_all(url, store), inline=False)
    await write_document(store, url, tree, existing=store.files[url], overwrite=True)
    assert store.files[url] == {"ome": ome, "sibling": 1}
    assert Document.from_content(url, store.files[url]).root == {
        k: v for k, v in ome.items() if k != "version"
    }
