"""Acceptance test: the Fall 2026 proposal examples open, inline and round-trip.

Loads the four commented JSON files in `docs/examples/rfc8-inner-node/proposal/`
(plus `image-b`, derived from `image-a`), lays them out as sibling Zarr groups in
a `MemoryStore`, and checks that a `ref` with a `path` reaches an *inner* node of
another document, that references are left bare by `open`, that errors surface
under `on_error="raise"`, and that an unedited document re-serializes identically.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import ngio_collections.api._api as aio
from ngio_collections.api import MemoryStore

PROPOSAL = Path(__file__).parent.parent / "docs/examples/rfc8-inner-node/proposal"

A0, A1, A2 = (f"0192f3a0-a000-7000-8000-0000000000a{i}" for i in range(3))
B0, B1, B2 = (f"0192f3a0-b000-7000-8000-0000000000b{i}" for i in range(3))
C0 = "0192f3a0-c000-7000-8000-0000000000c0"

X = "/x"


def _strip_jsonc(text: str) -> str:
    """Drop `//` line comments that sit outside string literals."""
    out: list[str] = []
    for line in text.splitlines():
        in_string = False
        for i, ch in enumerate(line):
            if ch == '"' and (i == 0 or line[i - 1] != "\\"):
                in_string = not in_string
            elif ch == "/" and not in_string and line[i : i + 2] == "//":
                line = line[:i]
                break
        out.append(line)
    return "\n".join(out)


def _load(name: str) -> dict:
    return json.loads(_strip_jsonc((PROPOSAL / f"{name}.jsonc").read_text()))


def _zarr_group(content: dict) -> dict:
    return {"zarr_format": 3, "node_type": "group", "attributes": content}


def _store(**overrides: dict) -> MemoryStore:
    """The sibling layout `/x/<name>/zarr.json`; `overrides` replace documents."""
    image_a = _load("image-a")
    image_b = json.loads(
        json.dumps(image_a).replace("a000-7000-8000-0000000000a", "b000-7000-8000-0000000000b")
    )
    docs = {
        "scene-a": _load("scene-a"),
        "scene-b": _load("scene-b"),
        "image-a": image_a,
        "image-b": image_b,
        "training-data": _load("training-data"),
        **overrides,
    }
    return MemoryStore({f"{X}/{name}/zarr.json": _zarr_group(doc) for name, doc in docs.items()})


async def test_open_leaves_three_references_without_ids() -> None:
    root = await aio.open(f"{X}/training-data", _store())
    assert root.id == C0 and root.name == "Training data"
    assert root.attributes == {"traits": []}
    children = root.children()
    assert [c.is_reference for c in children] == [True, True, True]
    assert [c.record.ref.ref for c in children] == [A1, B1, A2]
    assert [c.type for c in children] == ["collection", "collection", "multiscale"]
    assert [c.id for c in children] == [None, None, None]
    assert [c.ref_path for c in children] == ["../scene-a", "../scene-b", "../image-a"]
    assert root.find(A1) is None and root.tree.referrers(A1)


async def test_open_inlined_reaches_inner_nodes_and_their_images() -> None:
    view = await aio.open_inlined(f"{X}/training-data", _store(), on_error="raise")
    crop_a, crop_b, image_a = view.children()

    # the two inner `crop` collections, verbatim from their scene documents
    assert (crop_a.id, crop_b.id) == (A1, B1)
    assert crop_a.name == crop_b.name == "crop"
    assert crop_a.document_url == f"{X}/scene-a/zarr.json"
    assert crop_b.document_url == f"{X}/scene-b/zarr.json"
    assert view.find(A0) is None and view.find(B0) is None  # scene roots not mounted

    # ... each holding one multiscale, itself resolved through the scene
    (img_a,) = crop_a.children()
    (img_b,) = crop_b.children()
    for node, expected_id, url in ((img_a, A2, "image-a"), (img_b, B2, "image-b")):
        assert not node.is_reference and node.id == expected_id
        assert node.type == "multiscale" and node.children() == ()
        assert node.document_url == f"{X}/{url}/zarr.json"
        assert set(node.attributes) == {"coordinate_systems", "scales", "traits"}
        (scale,) = node.attributes["scales"]
        assert scale["path"] == {"type": "zarr", "format": "relative", "href": "./s0"}

    # the root of image-a, referenced by the same mechanism
    assert image_a.id == A2 and image_a.record == img_a.record
    assert view.tree.mode == "resolved"


async def test_depth_one_stops_inside_the_scenes() -> None:
    view = await aio.open_inlined(f"{X}/training-data", _store(), depth=1)
    crop_a, crop_b, image_a = view.children()
    assert crop_a.id == A1 and crop_b.id == B1 and image_a.id == A2
    (img_a,) = crop_a.children()
    assert img_a.is_reference and img_a.record.ref.ref == A2
    assert img_a.ref_path == "../image-a"


async def test_wrong_type_raises_type_error() -> None:
    variant = _load("training-data")
    variant["ome"]["nodes"][2]["type"] = "collection"  # image-a is a multiscale
    store = _store(**{"training-data": variant})
    with pytest.raises(TypeError):
        await aio.open_inlined(f"{X}/training-data", store, on_error="raise")
    skipped = await aio.open_inlined(f"{X}/training-data", store)
    assert skipped.children()[2].is_reference


async def test_unknown_ref_raises_lookup_error() -> None:
    variant = _load("training-data")
    variant["ome"]["nodes"][0]["ref"] = "0192f3a0-dead-7000-8000-000000000000"
    store = _store(**{"training-data": variant})
    with pytest.raises(LookupError):
        await aio.open_inlined(f"{X}/training-data", store, on_error="raise")
    skipped = await aio.open_inlined(f"{X}/training-data", store)
    assert skipped.children()[0].is_reference and skipped.children()[1].id == B1


async def test_save_round_trip_is_identical() -> None:
    store = _store()
    url = f"{X}/training-data/zarr.json"
    original = copy.deepcopy(await store.get(url))
    root = await aio.open(f"{X}/training-data", store)
    await aio.save(root, store)
    assert await store.get(url) == original

    scene = await aio.open(f"{X}/scene-a", store)
    scene_url = f"{X}/scene-a/zarr.json"
    before = copy.deepcopy(await store.get(scene_url))
    await aio.save(scene, store)
    assert await store.get(scene_url) == before
