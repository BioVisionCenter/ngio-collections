"""Tests for L3 resolution: the pure `build` and the async `fetch_all` shell.

`build` is exercised with hand-built in-memory `Document`s (no IO); `fetch_all` is
exercised against a tiny in-memory store, and the two are cross-checked so the
async shell and the pure core agree.
"""

from __future__ import annotations

import pytest

from ngio_collections.graph import ROOT
from ngio_collections.io import _json
from ngio_collections.resolve import Document, build, fetch_all, reference_targets

DATA = "/data"


def _doc(name: str, root: dict) -> Document:
    """A JSON `Document` at /data/<name>.json with `root` as its node tree."""
    return Document(url=f"{DATA}/{name}.json", kind="json", root=root)


def _stub(name: str, target: str, **extra: object) -> dict:
    """A cross-document stub node dict pointing at ./<target>.json."""
    return {
        "type": "multiscale",
        "name": name,
        "path": {"type": "json", "path": f"./{target}.json"},
        **extra,
    }


def _collection_with(*children: dict, id: str = "root") -> dict:
    """A collection root node dict wrapping `children`."""
    return {"type": "collection", "id": id, "nodes": list(children)}


def _image(id: str = "image", **attrs: object) -> dict:
    """A materialized multiscale node dict (the usual reference target)."""
    return {"type": "multiscale", "id": id, "attributes": dict(attrs)}


# --------------------------------------------------------------------------- #
# build: non-inline keeps stubs as references
# --------------------------------------------------------------------------- #


def test_open_leaves_stub_as_reference() -> None:
    entry = _doc("collection", _collection_with(_stub("img", "image")))
    docs = {entry.url: entry}
    c = build(entry.url, docs, inline=False)
    (key,) = c.children_ids(ROOT)
    rec = c.record(key)
    assert rec.is_reference and rec.ref is not None
    assert rec.ref.path.path == "./image.json"
    assert c.mode == "editable"


# --------------------------------------------------------------------------- #
# build: inline splices the target in, with overlay + name fallback
# --------------------------------------------------------------------------- #


def _inline_fixture() -> dict[str, Document]:
    entry = _doc(
        "collection",
        _collection_with(_stub("img", "image", attributes={"role": "raw"})),
    )
    target = _doc("image", _image(role="target", extra=1))
    return {entry.url: entry, target.url: target}


def test_open_inlined_merges_target_root() -> None:
    docs = _inline_fixture()
    c = build(f"{DATA}/collection.json", docs, inline=True)
    (key,) = c.children_ids(ROOT)
    rec = c.record(key)
    assert not rec.is_reference
    assert rec.type == "multiscale" and rec.id == "image"
    assert rec.name == "img"  # target has no name -> falls back to the stub
    assert dict(rec.attributes) == {"role": "raw", "extra": 1}  # stub wins
    assert rec.origin_url == f"{DATA}/image.json"
    assert c.mode == "resolved"


def test_inlined_boundary_node_retains_the_collapsed_edge() -> None:
    docs = _inline_fixture()
    c = build(f"{DATA}/collection.json", docs, inline=True)
    (key,) = c.children_ids(ROOT)
    edge = c.record(key).edge
    # the stub's own pre-merge values survive, so the merge is invertible
    assert edge is not None
    assert edge.ref.path.path == "./image.json" and edge.ref.id is None
    assert dict(edge.attributes) == {"role": "raw"}  # stub overlay only
    assert edge.name == "img"
    assert edge.origin_url == f"{DATA}/collection.json"  # declaring document
    # non-boundary nodes carry no edge
    assert c.record(ROOT).edge is None


def test_materialized_and_reference_records_have_no_edge() -> None:
    entry = _doc("collection", _collection_with(_stub("img", "image"), _image()))
    c = build(entry.url, {entry.url: entry}, inline=False)
    assert all(c.record(k).edge is None for k in c.walk())


def test_depth_zero_disables_inlining() -> None:
    docs = _inline_fixture()
    c = build(f"{DATA}/collection.json", docs, inline=True, depth=0)
    (key,) = c.children_ids(ROOT)
    assert c.record(key).is_reference


def test_missing_target_skips_or_raises() -> None:
    entry = _doc("collection", _collection_with(_stub("img", "image")))
    docs = {entry.url: entry}  # target image.json not fetched
    skipped = build(entry.url, docs, inline=True, on_error="skip")
    (key,) = skipped.children_ids(ROOT)
    assert skipped.record(key).is_reference
    with pytest.raises(FileNotFoundError):
        build(entry.url, docs, inline=True, on_error="raise")


def test_type_mismatch_skips_or_raises() -> None:
    entry = _doc("collection", _collection_with(_stub("img", "image")))
    target = _doc("image", {"type": "collection", "id": "image"})  # not multiscale
    docs = {entry.url: entry, target.url: target}
    skipped = build(entry.url, docs, inline=True)
    (key,) = skipped.children_ids(ROOT)
    assert skipped.record(key).is_reference
    with pytest.raises(TypeError):
        build(entry.url, docs, inline=True, on_error="raise")


def test_cycle_terminates_and_leaves_stub() -> None:
    entry = _doc(
        "collection",
        {
            "type": "collection",
            "id": "root",
            "nodes": [
                {
                    "type": "collection",
                    "name": "a",
                    "path": {"type": "json", "path": "./a.json"},
                }
            ],
        },
    )
    a = _doc(
        "a",
        {
            "type": "collection",
            "id": "a",
            "nodes": [
                {
                    "type": "collection",
                    "name": "back",
                    "path": {"type": "json", "path": "./collection.json"},
                }
            ],
        },
    )
    docs = {entry.url: entry, a.url: a}
    c = build(entry.url, docs, inline=True)
    (a_key,) = c.children_ids(ROOT)
    assert c.record(a_key).id == "a"  # a inlined
    (back_key,) = c.children_ids(a_key)
    assert c.record(back_key).is_reference  # the cycle back to entry stays a stub


def test_same_document_inlined_twice_yields_distinct_pristine_nodes() -> None:
    entry = _doc(
        "collection",
        _collection_with(_stub("one", "image"), _stub("two", "image")),
    )
    target = _doc("image", _image())
    docs = {entry.url: entry, target.url: target}
    c = build(entry.url, docs, inline=True)
    a, b = c.children_ids(ROOT)
    assert a != b
    assert set(c.find("image")) == {a, b}  # both materialized, id never rewritten
    assert c.record(a).id == c.record(b).id == "image"


# --------------------------------------------------------------------------- #
# fetch_all (async shell) + cross-check with the pure build
# --------------------------------------------------------------------------- #


class _MemoryStore:
    """A minimal in-memory ReadableStore for tests (url -> bytes)."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    async def get(self, url: str) -> bytes:
        """Return the bytes at `url`, raising FileNotFoundError if absent."""
        try:
            return self.files[url]
        except KeyError as exc:
            raise FileNotFoundError(url) from exc


def _store(*docs: Document) -> _MemoryStore:
    """Pack `Document`s into a store as their JSON-enveloped bytes."""
    return _MemoryStore({d.url: _json.dumps({"ome": d.root}) for d in docs})


async def test_fetch_all_gathers_transitive_documents() -> None:
    entry = _doc("collection", _collection_with(_stub("img", "image")))
    target = _doc("image", _image())
    store = _store(entry, target)
    docs = await fetch_all(entry.url, store)
    assert set(docs) == {entry.url, target.url}


async def test_fetch_then_build_matches_manual_docs() -> None:
    entry = _doc(
        "collection",
        _collection_with(_stub("img", "image", attributes={"role": "raw"})),
    )
    target = _doc("image", _image(role="target", extra=1))
    fetched = await fetch_all(entry.url, _store(entry, target))
    manual = {entry.url: entry, target.url: target}
    from_fetched = build(entry.url, fetched, inline=True)
    from_manual = build(entry.url, manual, inline=True)
    walk_fetched = [from_fetched.record(n).id for n in from_fetched.walk()]
    walk_manual = [from_manual.record(n).id for n in from_manual.walk()]
    assert walk_fetched == walk_manual


async def test_fetch_all_depth_zero_reads_only_entry() -> None:
    entry = _doc("collection", _collection_with(_stub("img", "image")))
    target = _doc("image", _image())
    docs = await fetch_all(entry.url, _store(entry, target), depth=0)
    assert set(docs) == {entry.url}


def test_reference_targets_lists_outgoing_urls() -> None:
    entry = _doc(
        "collection", _collection_with(_stub("a", "image"), _stub("b", "labels"))
    )
    assert set(reference_targets(entry)) == {
        f"{DATA}/image.json",
        f"{DATA}/labels.json",
    }
