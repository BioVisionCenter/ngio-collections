"""Tests for the L1 write path: serialize a NodeTree back to documents.

Covers payload shape, reference-stub round-trip, path relativization, and a full
build → write → re-read → build round-trip through a writable in-memory store.
"""

from __future__ import annotations

from ngio_collections.graph import ROOT, NodeTree, NodeRecord, Reference
from ngio_collections.io import _json
from ngio_collections.models._paths import ZarrPath
from ngio_collections.resolve import (
    Document,
    build,
    fetch_all,
    node_dict,
    payload,
    write_document,
)

DATA = "/data"


class _MemoryStore:
    """A minimal writable in-memory store (url -> bytes)."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def get(self, url: str) -> bytes:
        """Return the bytes at `url`, raising FileNotFoundError if absent."""
        try:
            return self.files[url]
        except KeyError as exc:
            raise FileNotFoundError(url) from exc

    async def put(self, url: str, data: bytes) -> None:
        """Store `data` at `url`."""
        self.files[url] = data

    async def delete(self, url: str) -> None:
        """Delete `url` if present."""
        self.files.pop(url, None)


# --------------------------------------------------------------------------- #
# payload / node_dict shape
# --------------------------------------------------------------------------- #


def _sample_collection() -> NodeTree:
    c = NodeTree.of(NodeRecord(type="collection", id="root", children=()))
    c, img = c.add_child(
        ROOT, NodeRecord(type="multiscale", id="img", attributes={"role": "raw"}, children=())
    )
    c, _ = c.add_child(img, NodeRecord(type="singlescale", id="0", children=()))
    return c


def test_payload_rebuilds_nesting_and_drops_empties() -> None:
    body = payload(_sample_collection(), base_url=f"{DATA}/c.json", relativize=False)
    assert body["version"]  # envelope stamped
    assert body["type"] == "collection" and body["id"] == "root"
    (img,) = body["nodes"]
    assert img["id"] == "img" and img["attributes"] == {"role": "raw"}
    assert "name" not in img  # None dropped
    (zero,) = img["nodes"]
    assert zero["id"] == "0" and "attributes" not in zero  # empty bag dropped


def test_reference_record_serializes_as_path_stub() -> None:
    c = NodeTree.of(NodeRecord(type="collection", id="root", children=()))
    c, _ = c.add_child(
        ROOT,
        NodeRecord(
            type="multiscale",
            name="img",
            ref=Reference(path=ZarrPath(path="../image.zarr"), id="image"),
        ),
    )
    body = payload(c, base_url=f"{DATA}/c.json", relativize=False)
    (stub,) = body["nodes"]
    assert stub["path"] == {"type": "zarr", "path": "../image.zarr"}
    assert "nodes" not in stub


def test_relativize_rewrites_absolute_stub_path() -> None:
    c = NodeTree.of(NodeRecord(type="collection", id="root", children=()))
    c, _ = c.add_child(
        ROOT,
        NodeRecord(
            type="multiscale",
            ref=Reference(path=ZarrPath(path="/data/image.zarr")),
        ),
    )
    body = payload(c, base_url=f"{DATA}/c.json", relativize=True)
    (stub,) = body["nodes"]
    assert stub["path"]["path"] == "./image.zarr"  # relativized against /data/


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
    assert dict(reread.record(reread.find("img")[0]).attributes) == {"role": "raw"}


async def test_unedited_write_is_byte_identical_on_resave() -> None:
    store = _MemoryStore()
    url = await write_document(store, f"{DATA}/c.json", _sample_collection())
    first = store.files[url]
    reread = build(url, await fetch_all(url, store), inline=False)
    await write_document(store, url, reread, existing=_json.loads(first))
    assert store.files[url] == first
