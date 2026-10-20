"""Tests for resolution: the pure `build` and the async `fetch_all` shell.

`build` is exercised with hand-built in-memory `Document`s (no IO) and with the
revision fixtures through a `MemoryStore`; `fetch_all` is cross-checked against
the pure core so the async shell and the build agree.
"""

from __future__ import annotations

import pytest

from ngio_collections.graph import ROOT
from ngio_collections.models._paths import CORE_FORMATS
from ngio_collections.resolve import (
    CycleError,
    Document,
    IdMismatchError,
    TypeMismatchError,
    build,
    fetch_all,
    reference_targets,
    trait_reference_targets,
)
from tests.conftest import DATA, mk

RENDER = "https://napari.org/ngff/rendering"
SCALES = {
    "coordinate_systems": [
        {"type": "coordinate_system", "id": mk(0x20), "axes": [{"name": "x"}]}
    ],
    "scales": [
        {
            "type": "scale",
            "id": mk(0xC),
            "path": {"type": "zarr", "format": "relative", "href": "./s0"},
        }
    ],
}


def _doc(name: str, root: dict) -> Document:
    """A JSON `Document` at /data/<name>.json with `root` as its node tree."""
    return Document(url=f"{DATA}/{name}.json", kind="json", root=root)


def _stub(n: int, target: str, *, type: str = "multiscale", **extra: object) -> dict:
    """A declaring entry pointing at ./<target>.json."""
    return {
        "type": type,
        "id": mk(n),
        "path": {"type": "json", "format": "relative", "href": f"./{target}.json"},
        **extra,
    }


def _collection(*children: dict, n: int = 0) -> dict:
    return {"type": "collection", "id": mk(n), "name": f"c{n}", "nodes": list(children)}


def _image(n: int = 1, *traits: dict, **extra: object) -> dict:
    """A multiscale document root (the usual target)."""
    root: dict = {"type": "multiscale", "id": mk(n), **SCALES, **extra}
    if traits:
        root["traits"] = list(traits)
    return root


# --------------------------------------------------------------------------- #
# build: non-inline keeps external nodes
# --------------------------------------------------------------------------- #


def test_open_leaves_external_node() -> None:
    entry = _doc("collection", _collection(_stub(1, "image")))
    c = build(entry.url, {entry.url: entry}, inline=False)
    (key,) = c.children_ids(ROOT)
    rec = c.record(key)
    assert rec.is_external and rec.path is not None
    assert rec.path.href == "./image.json" and rec.path.format == "relative"
    assert rec.id == mk(1) and c.mode == "editable"


def test_malformed_nodes_are_rejected() -> None:
    no_id = _doc("c", _collection({"type": "collection", "nodes": []}))
    with pytest.raises(ValueError):
        build(no_id.url, {no_id.url: no_id}, inline=False)
    both = _doc("c", _collection({**_stub(1, "x", type="collection"), "nodes": []}))
    with pytest.raises(ValueError):
        build(both.url, {both.url: both}, inline=False)
    dup = _doc(
        "c",
        {
            **_collection(),
            "traits": [
                {"type": "well", "row_index": 0, "column_index": 0},
                {"type": "well", "row_index": 1, "column_index": 1},
            ],
        },
    )
    with pytest.raises(ValueError):
        build(dup.url, {dup.url: dup}, inline=False)


def test_node_fields_and_traits_are_split() -> None:
    entry = _doc(
        "image", _image(1, {"type": "labels", "source": []}, name="raw", version="0.x")
    )
    c = build(entry.url, {entry.url: entry}, inline=False)
    root = c.record(ROOT)
    assert root.name == "raw"
    assert list(root.traits) == ["labels"]
    assert set(root.fields) == {"coordinate_systems", "scales", "version"}
    assert c.declarations(mk(0xC)) == (ROOT,) and c.declarations(mk(0x20)) == (ROOT,)


# --------------------------------------------------------------------------- #
# build: inline splices the target in, traits combine (entry wins per type)
# --------------------------------------------------------------------------- #


def _inline_fixture() -> dict[str, Document]:
    entry = _doc(
        "collection",
        _collection(
            _stub(
                1,
                "image",
                name="img",
                traits=[
                    {"type": RENDER, "contrast_limits": [0, 1]},
                    {"type": "well", "row_index": 0, "column_index": 0},
                ],
            )
        ),
    )
    target = _doc(
        "image",
        _image(
            1,
            {"type": RENDER, "contrast_limits": [5, 6], "gamma": 1},
            {"type": "labels", "source": []},
            name="raw",
        ),
    )
    return {entry.url: entry, target.url: target}


def test_resolved_merges_target_root_with_entry_traits_winning() -> None:
    docs = _inline_fixture()
    c = build(f"{DATA}/collection.json", docs, inline=True)
    (key,) = c.children_ids(ROOT)
    rec = c.record(key)
    assert not rec.is_external and rec.type == "multiscale" and rec.id == mk(1)
    assert rec.name == "img"  # the declaring entry's name wins
    assert list(rec.traits) == [
        RENDER,
        "labels",
        "well",
    ]  # target order, extra appended
    assert rec.traits[RENDER] == {
        "type": RENDER,
        "contrast_limits": [0, 1],
    }  # whole trait
    assert set(rec.fields) == {"coordinate_systems", "scales"}  # never merged
    assert rec.origin_url == f"{DATA}/image.json"
    assert c.mode == "resolved"
    assert c.declarations(mk(0xC)) == (key,)


def test_target_name_used_when_entry_has_none() -> None:
    entry = _doc("collection", _collection(_stub(1, "image")))
    target = _doc("image", _image(1, name="raw"))
    c = build(entry.url, {entry.url: entry, target.url: target}, inline=True)
    (key,) = c.children_ids(ROOT)
    assert c.record(key).name == "raw"


def test_resolved_boundary_node_retains_the_edge() -> None:
    docs = _inline_fixture()
    c = build(f"{DATA}/collection.json", docs, inline=True)
    (key,) = c.children_ids(ROOT)
    edge = c.record(key).edge
    assert edge is not None
    assert edge.path.href == "./image.json"
    assert list(edge.traits) == [RENDER, "well"]  # the entry's own traits only
    assert edge.name == "img" and edge.fields == {}
    assert edge.origin_url == f"{DATA}/collection.json"
    assert c.record(ROOT).edge is None


def test_depth_zero_disables_resolution() -> None:
    docs = _inline_fixture()
    c = build(f"{DATA}/collection.json", docs, inline=True, depth=0)
    (key,) = c.children_ids(ROOT)
    assert c.record(key).is_external


def test_missing_target_skips_or_raises() -> None:
    entry = _doc("collection", _collection(_stub(1, "image")))
    docs = {entry.url: entry}
    skipped = build(entry.url, docs, inline=True, on_error="skip")
    (key,) = skipped.children_ids(ROOT)
    assert skipped.record(key).is_external
    with pytest.raises(FileNotFoundError):
        build(entry.url, docs, inline=True, on_error="raise")


def test_type_mismatch_skips_or_raises() -> None:
    entry = _doc("collection", _collection(_stub(1, "image")))
    target = _doc("image", _collection(n=1))  # a collection, not a multiscale
    docs = {entry.url: entry, target.url: target}
    (key,) = build(entry.url, docs, inline=True).children_ids(ROOT)
    assert build(entry.url, docs, inline=True).record(key).is_external
    with pytest.raises(TypeMismatchError):
        build(entry.url, docs, inline=True, on_error="raise")


def test_id_mismatch_skips_or_raises() -> None:
    entry = _doc("collection", _collection(_stub(1, "image")))
    target = _doc("image", _image(2))  # root id differs from the entry's
    docs = {entry.url: entry, target.url: target}
    (key,) = build(entry.url, docs, inline=True).children_ids(ROOT)
    assert build(entry.url, docs, inline=True).record(key).is_external
    with pytest.raises(IdMismatchError):
        build(entry.url, docs, inline=True, on_error="raise")


def test_payload_free_target_is_a_terminal_leaf() -> None:
    # A node whose `path` locates plain data (a Zarr array): nothing to resolve,
    # nothing wrong, under either policy. Contrast the missing-target case.
    entry = _doc("collection", _collection(_stub(1, "s0")))
    target = Document(url=f"{DATA}/s0.json", kind="json", root={}, has_payload=False)
    docs = {entry.url: entry, target.url: target}
    for on_error in ("skip", "raise"):
        c = build(entry.url, docs, inline=True, on_error=on_error)
        (key,) = c.children_ids(ROOT)
        assert c.record(key).is_external


def test_present_but_typeless_payload_still_raises() -> None:
    entry = _doc("collection", _collection(_stub(1, "image")))
    target = _doc("image", {"id": mk(1)})  # `ome` present, no `type`
    with pytest.raises(TypeMismatchError):
        build(
            entry.url,
            {entry.url: entry, target.url: target},
            inline=True,
            on_error="raise",
        )


def test_payload_free_entry_document_raises() -> None:
    doc = Document.from_content(
        "/data/s0.zarr", {"zarr_format": 3, "node_type": "array"}
    )
    assert doc.has_payload is False and doc.root == {}
    assert list(reference_targets(doc)) == []
    with pytest.raises(ValueError):
        build(doc.url, {doc.url: doc}, inline=False)


def test_cycle_leaves_node_external_or_raises() -> None:
    entry = _doc("collection", _collection(_stub(1, "a", type="collection")))
    a = _doc("a", _collection(_stub(0, "collection", type="collection"), n=1))
    docs = {entry.url: entry, a.url: a}
    c = build(entry.url, docs, inline=True)
    (a_key,) = c.children_ids(ROOT)
    assert c.record(a_key).id == mk(1) and not c.record(a_key).is_external
    (back_key,) = c.children_ids(a_key)
    assert c.record(back_key).is_external  # the hop back to the entry stays external
    with pytest.raises(CycleError):
        build(entry.url, docs, inline=True, on_error="raise")


def test_same_document_resolved_twice_yields_distinct_nodes() -> None:
    entry = _doc("collection", _collection(_stub(1, "image"), _stub(1, "image")))
    target = _doc("image", _image(1))
    c = build(entry.url, {entry.url: entry, target.url: target}, inline=True)
    a, b = c.children_ids(ROOT)
    assert a != b and set(c.find(mk(1))) == {a, b}
    assert c.record(a).id == c.record(b).id == mk(1)


def test_unsupported_format_leaves_node_external_under_core_formats() -> None:
    remote = {
        "type": "multiscale",
        "id": mk(1),
        "path": {"type": "zarr", "format": "http", "href": "https://h.org/ref.zarr"},
    }
    entry = _doc("collection", _collection(remote))
    docs = {entry.url: entry}
    # strict: unavailable, never an error
    c = build(entry.url, docs, inline=True, on_error="raise", formats=CORE_FORMATS)
    (key,) = c.children_ids(ROOT)
    assert c.record(key).is_external
    # default (deviation): resolvable, so a missing document is reported
    with pytest.raises(FileNotFoundError):
        build(entry.url, docs, inline=True, on_error="raise")


# --------------------------------------------------------------------------- #
# Document envelope
# --------------------------------------------------------------------------- #


def test_document_strips_version_and_manifest() -> None:
    content = {
        "attributes": {
            "ome": {
                "version": "0.x",
                "extension_manifest": [{"id": "https://x.org/", "version": "1"}],
                "type": "collection",
                "id": mk(1),
                "nodes": [],
            }
        }
    }
    doc = Document.from_content("/data/c.zarr", content)
    assert doc.kind == "zarr" and doc.url == "/data/c.zarr/zarr.json"
    assert doc.ref_url == "/data/c.zarr"
    assert set(doc.root) == {"type", "id", "nodes"}
    assert doc.extension_manifest == ({"id": "https://x.org/", "version": "1"},)


# --------------------------------------------------------------------------- #
# fetch_all + the revision fixtures
# --------------------------------------------------------------------------- #


async def test_fetch_all_gathers_transitive_documents_and_manifests(
    revision_store,
) -> None:
    url = f"{DATA}/collection/zarr.json"
    docs = await fetch_all(url, revision_store)
    # raw and nuclei are reachable; the http node is not in the memory store
    assert set(docs) == {
        url,
        f"{DATA}/collection/raw/zarr.json",
        f"{DATA}/collection/nuclei/zarr.json",
    }
    assert docs[url].extension_manifest[0]["id"] == "https://napari.org/ngff/"
    shallow = await fetch_all(url, revision_store, depth=0)
    assert set(shallow) == {url}
    reused = await fetch_all(url, revision_store, docs=docs)
    assert reused == docs


async def test_revision_collection_resolves(revision_store) -> None:
    url = f"{DATA}/collection/zarr.json"
    c = build(url, await fetch_all(url, revision_store), inline=True)
    raw, nuclei, remote = (c.record(k) for k in c.children_ids(ROOT))
    assert not raw.is_external and raw.traits[RENDER]["contrast_limits"] == [0, 1500]
    assert [s["id"] for s in raw.fields["scales"]] == [mk(0xC), mk(0xD)]
    assert not nuclei.is_external and "labels" in nuclei.traits
    assert (
        remote.is_external and remote.path is not None and remote.path.format == "http"
    )
    assert c.manifests[url][0]["id"] == "https://napari.org/ngff/"
    assert c.declarations(mk(0x20)) == (c.children_ids(ROOT)[0],)


async def test_bad_fixtures_report_their_defect(revision_store) -> None:
    base = f"{DATA}/bad"
    with pytest.raises(IdMismatchError):
        url = f"{base}/id_mismatch/zarr.json"
        build(url, await fetch_all(url, revision_store), inline=True, on_error="raise")
    with pytest.raises(TypeMismatchError):
        url = f"{base}/type_mismatch/zarr.json"
        build(url, await fetch_all(url, revision_store), inline=True, on_error="raise")
    with pytest.raises(CycleError):
        url = f"{base}/cycle/a.json"
        build(url, await fetch_all(url, revision_store), inline=True, on_error="raise")
    for name in ("duplicate_trait", "nodes_and_path"):
        url = f"{base}/{name}/zarr.json"
        with pytest.raises(ValueError):
            build(url, await fetch_all(url, revision_store), inline=False)


def test_reference_targets_lists_node_paths_and_trait_refs() -> None:
    scene = {
        "type": "scene",
        "coordinate_transformations": [
            {
                "type": "translation",
                "translation": [0, 0],
                "input": {
                    "type": "coordinate_system",
                    "ref": mk(0x20),
                    "path": {"type": "zarr", "format": "relative", "href": "./raw"},
                },
                "output": {"type": "coordinate_system", "ref": mk(5)},
            }
        ],
    }
    entry = _doc(
        "collection",
        {**_collection(_stub(1, "image"), _stub(2, "labels")), "traits": [scene]},
    )
    assert set(reference_targets(entry)) == {
        f"{DATA}/image.json",
        f"{DATA}/labels.json",
    }
    assert list(trait_reference_targets(entry)) == [f"{DATA}/raw/zarr.json"]
