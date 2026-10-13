"""Tests for L3 resolution: the pure `build` and the async `fetch_all` shell.

`build` is exercised with hand-built in-memory `Document`s (no IO); `fetch_all` is
exercised against a tiny in-memory store, and the two are cross-checked so the
async shell and the pure core agree.
"""

from __future__ import annotations

import pytest
from conftest import uid

from ngio_collections.graph import ROOT
from ngio_collections.resolve import (
    Document,
    build,
    fetch_all,
    payload,
    reference_targets,
)

DATA = "/data"


def _doc(name: str, root: dict) -> Document:
    """A JSON `Document` at /data/<name>.json with `root` as its node tree."""
    return Document(url=f"{DATA}/{name}.json", kind="json", root=root)


def _path(target: str) -> dict:
    return {"type": "json", "format": "relative", "href": f"./{target}.json"}


def _ref(target_id: str, target: str | None = None, type: str = "multiscale") -> dict:
    """A reference entry pointing at `target_id`, inside ./<target>.json if given."""
    entry: dict = {"type": type, "ref": uid(target_id)}
    if target is not None:
        entry["path"] = _path(target)
    return entry


def _collection(*children: dict, id: str = "root", **body: object) -> dict:
    """A collection declaration wrapping `children`."""
    return {
        "type": "collection",
        "id": uid(id),
        "name": id,
        **body,
        "nodes": list(children),
    }


def _image(id: str = "image", **body: object) -> dict:
    """A multiscale declaration (a leaf; its body holds e.g. `scales`)."""
    return {"type": "multiscale", "id": uid(id), **body}


# --------------------------------------------------------------------------- #
# build: declarations vs references
# --------------------------------------------------------------------------- #


def test_open_leaves_reference_in_place() -> None:
    entry = _doc("collection", _collection(_ref("image", "image")))
    c = build(entry.url, {entry.url: entry}, inline=False)
    (key,) = c.children_ids(ROOT)
    rec = c.record(key)
    assert rec.is_reference and rec.ref is not None
    assert rec.ref.ref == uid("image")
    assert rec.ref.path is not None and rec.ref.path.href == "./image.json"
    assert rec.id is None and rec.name is None and not rec.attributes
    assert c.mode == "editable"


def test_body_is_every_non_structural_key() -> None:
    root = _collection(
        _image(scales=[{"id": uid("s0")}], coordinate_systems=[], traits=[]),
        traits=[{"kind": "x"}],
    )
    entry = _doc("collection", root)
    c = build(entry.url, {entry.url: entry}, inline=False)
    assert dict(c.record(ROOT).attributes) == {"traits": [{"kind": "x"}]}
    (img,) = c.children_ids(ROOT)
    rec = c.record(img)
    assert rec.is_leaf and list(rec.attributes) == ["scales", "coordinate_systems", "traits"]
    assert rec.id == uid("image")


@pytest.mark.parametrize("on_error", ["skip", "raise"])
def test_both_or_neither_of_id_and_ref_is_a_document_error(on_error) -> None:
    both = {"type": "multiscale", "id": uid("a"), "ref": uid("b"), "path": _path("x")}
    neither = {"type": "multiscale", "name": "anonymous"}
    for bad in (both, neither):
        entry = _doc("collection", _collection(bad))
        for inline in (False, True):
            with pytest.raises(ValueError):
                build(entry.url, {entry.url: entry}, inline=inline, on_error=on_error)


def test_bare_ref_is_left_in_place_and_serializes_back() -> None:
    entry = _doc("collection", _collection(_image(), _ref("image")))
    docs = {entry.url: entry}
    for inline in (False, True):
        c = build(entry.url, docs, inline=inline, on_error="raise")
        img, bare = c.children_ids(ROOT)
        assert c.record(img).is_leaf
        rec = c.record(bare)
        assert rec.is_reference and rec.ref is not None and rec.ref.path is None
        assert c.referrers(uid("image")) == (bare,)
    body = payload(c, base_url=entry.url)
    assert body["nodes"][1] == {"type": "multiscale", "ref": uid("image")}


# --------------------------------------------------------------------------- #
# build: inline splices the found declaration in, verbatim
# --------------------------------------------------------------------------- #


def _inline_fixture() -> dict[str, Document]:
    entry = _doc("collection", _collection(_ref("image", "image")))
    target = _doc("image", _image(name="Image", role="target", extra=1))
    return {entry.url: entry, target.url: target}


def test_open_inlined_splices_the_declaration() -> None:
    docs = _inline_fixture()
    c = build(f"{DATA}/collection.json", docs, inline=True)
    (key,) = c.children_ids(ROOT)
    rec = c.record(key)
    assert not rec.is_reference and rec.is_leaf
    assert rec.type == "multiscale" and rec.id == uid("image")
    assert rec.name == "Image"  # the referenced node brings its own name
    assert dict(rec.attributes) == {"role": "target", "extra": 1}  # ... and body
    assert rec.origin_url == f"{DATA}/image.json"
    assert c.find(uid("image")) == (key,) and c.referrers(uid("image")) == ()
    assert c.mode == "resolved"


def test_ref_with_path_reaches_an_inner_node() -> None:
    inner = _collection(_image("deep"), id="crop", traits=["t"])
    scene = _doc("scene", _collection(inner, id="scene"))
    entry = _doc("entry", _collection(_ref("crop", "scene", type="collection")))
    docs = {entry.url: entry, scene.url: scene}
    c = build(entry.url, docs, inline=True, on_error="raise")
    (crop_key,) = c.children_ids(ROOT)
    crop = c.record(crop_key)
    assert crop.id == uid("crop") and crop.name == "crop" and crop.is_branch
    assert dict(crop.attributes) == {"traits": ["t"]}
    assert crop.origin_url == scene.url
    (deep_key,) = c.children_ids(crop_key)
    assert c.record(deep_key).id == uid("deep")
    assert c.find(uid("scene")) == ()  # the scene root itself was not mounted


def test_lookup_is_not_transitive_through_references() -> None:
    # entry -> scene, which only *references* image; `ref` to image's id via
    # scene must not crawl into image.json.
    scene = _doc("scene", _collection(_ref("image", "image"), id="scene"))
    image = _doc("image", _image())
    entry = _doc("entry", _collection(_ref("image", "scene")))
    docs = {entry.url: entry, scene.url: scene, image.url: image}
    c = build(entry.url, docs, inline=True)
    (key,) = c.children_ids(ROOT)
    assert c.record(key).is_reference
    with pytest.raises(LookupError):
        build(entry.url, docs, inline=True, on_error="raise")


def test_depth_zero_disables_inlining() -> None:
    docs = _inline_fixture()
    c = build(f"{DATA}/collection.json", docs, inline=True, depth=0)
    (key,) = c.children_ids(ROOT)
    assert c.record(key).is_reference


def test_missing_target_skips_or_raises() -> None:
    entry = _doc("collection", _collection(_ref("image", "image")))
    docs = {entry.url: entry}  # target image.json not fetched
    skipped = build(entry.url, docs, inline=True, on_error="skip")
    (key,) = skipped.children_ids(ROOT)
    assert skipped.record(key).is_reference
    with pytest.raises(FileNotFoundError):
        build(entry.url, docs, inline=True, on_error="raise")


def test_unknown_ref_skips_or_raises() -> None:
    entry = _doc("collection", _collection(_ref("absent", "image")))
    target = _doc("image", _image())
    docs = {entry.url: entry, target.url: target}
    skipped = build(entry.url, docs, inline=True)
    (key,) = skipped.children_ids(ROOT)
    assert skipped.record(key).is_reference
    with pytest.raises(LookupError):
        build(entry.url, docs, inline=True, on_error="raise")


def test_type_mismatch_skips_or_raises() -> None:
    entry = _doc("collection", _collection(_ref("image", "image")))
    target = _doc("image", {"type": "collection", "id": uid("image"), "nodes": []})
    docs = {entry.url: entry, target.url: target}
    skipped = build(entry.url, docs, inline=True)
    (key,) = skipped.children_ids(ROOT)
    assert skipped.record(key).is_reference
    with pytest.raises(TypeError):
        build(entry.url, docs, inline=True, on_error="raise")


def test_payload_free_target_is_unresolvable() -> None:
    # A plain Zarr array has no `ome` payload, hence declares nothing.
    entry = _doc("collection", _collection(_ref("s0", "s0")))
    target = Document(url=f"{DATA}/s0.json", kind="json", root={}, has_payload=False)
    docs = {entry.url: entry, target.url: target}
    c = build(entry.url, docs, inline=True, on_error="skip")
    (key,) = c.children_ids(ROOT)
    assert c.record(key).is_reference
    with pytest.raises(LookupError):
        build(entry.url, docs, inline=True, on_error="raise")


def test_payload_free_entry_document_raises() -> None:
    content = {"zarr_format": 3, "node_type": "array"}  # a plain Zarr array
    doc = Document.from_content("/data/s0.zarr", content)
    assert doc.has_payload is False
    assert doc.root == {}
    assert list(reference_targets(doc)) == []
    with pytest.raises(ValueError):
        build(doc.url, {doc.url: doc}, inline=False)


def test_cycle_terminates_and_leaves_reference() -> None:
    entry = _doc("collection", _collection(_ref("a", "a", type="collection")))
    a = _doc("a", _collection(_ref("root", "collection", type="collection"), id="a"))
    docs = {entry.url: entry, a.url: a}
    c = build(entry.url, docs, inline=True)
    (a_key,) = c.children_ids(ROOT)
    assert c.record(a_key).id == uid("a")  # a inlined
    (back_key,) = c.children_ids(a_key)
    assert c.record(back_key).is_reference  # the cycle back to entry stays


def test_same_document_inlined_twice_yields_distinct_pristine_nodes() -> None:
    entry = _doc(
        "collection", _collection(_ref("image", "image"), _ref("image", "image"))
    )
    target = _doc("image", _image())
    docs = {entry.url: entry, target.url: target}
    c = build(entry.url, docs, inline=True)
    a, b = c.children_ids(ROOT)
    assert a != b
    assert set(c.find(uid("image"))) == {a, b}  # both materialized, id never rewritten
    assert c.record(a).id == c.record(b).id == uid("image")


# --------------------------------------------------------------------------- #
# fetch_all (async shell) + cross-check with the pure build
# --------------------------------------------------------------------------- #


class _MemoryStore:
    """A minimal in-memory ReadableStore for tests (url -> dict)."""

    def __init__(self, files: dict[str, dict]) -> None:
        self.files = files

    async def get(self, url: str) -> dict:
        """Return the document at `url`, raising FileNotFoundError if absent."""
        try:
            return self.files[url]
        except KeyError as exc:
            raise FileNotFoundError(url) from exc


def _store(*docs: Document) -> _MemoryStore:
    """Pack `Document`s into a store as their JSON-enveloped content."""
    return _MemoryStore({d.url: {"ome": d.root} for d in docs})


async def test_fetch_all_gathers_transitive_documents() -> None:
    entry = _doc("collection", _collection(_ref("image", "image")))
    target = _doc("image", _image())
    store = _store(entry, target)
    docs = await fetch_all(entry.url, store)
    assert set(docs) == {entry.url, target.url}


async def test_fetch_then_build_matches_manual_docs() -> None:
    entry = _doc("collection", _collection(_ref("image", "image")))
    target = _doc("image", _image(role="target", extra=1))
    fetched = await fetch_all(entry.url, _store(entry, target))
    manual = {entry.url: entry, target.url: target}
    from_fetched = build(entry.url, fetched, inline=True)
    from_manual = build(entry.url, manual, inline=True)
    walk_fetched = [from_fetched.record(n).id for n in from_fetched.walk()]
    walk_manual = [from_manual.record(n).id for n in from_manual.walk()]
    assert walk_fetched == walk_manual


async def test_fetch_all_depth_zero_reads_only_entry() -> None:
    entry = _doc("collection", _collection(_ref("image", "image")))
    target = _doc("image", _image())
    docs = await fetch_all(entry.url, _store(entry, target), depth=0)
    assert set(docs) == {entry.url}


def test_reference_targets_lists_outgoing_urls_not_body_paths() -> None:
    entry = _doc(
        "collection",
        _collection(
            _ref("a", "image"),
            _ref("b", "labels"),
            _ref("c"),  # bare ref: nothing to fetch
            _image(scales=[{"id": uid("s0"), "path": _path("s0")}]),  # body path
        ),
    )
    assert set(reference_targets(entry)) == {
        f"{DATA}/image.json",
        f"{DATA}/labels.json",
    }
