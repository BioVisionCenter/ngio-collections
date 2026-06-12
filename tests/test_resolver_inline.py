"""Resolver.inline(): explicit copy-building merge of a resolved tree into
one document, materializing the DESIGN.md §5 attribute merge."""

import json
from pathlib import Path

import pytest

import ome_zarr_collections as ozc
from ome_zarr_collections import parse_metadata_document

REFERENCE_DIR = Path(__file__).parent / "data"


class CountingStore(ozc.LocalStore):
    """LocalStore that counts get() calls, to assert cache hits."""

    def __init__(self):
        self.gets = 0

    async def get(self, url: str) -> bytes:
        self.gets += 1
        return await super().get(url)


@pytest.fixture
def resolver():
    return ozc.Resolver(ozc.LocalStore())


def _collection(node_id: str, *nodes: dict, attributes: dict | None = None) -> dict:
    payload = {
        "version": "0.x",
        "type": "collection",
        "id": node_id,
        "name": node_id,
        "nodes": list(nodes),
    }
    if attributes is not None:
        payload["attributes"] = attributes
    return {"ome": payload}


def _stub(
    node_id: str,
    path: str,
    *,
    path_type: str = "json",
    attributes: dict | None = None,
) -> dict:
    stub = {
        "type": "collection",
        "id": node_id,
        "name": node_id,
        "path": {"type": path_type, "path": path},
    }
    if attributes is not None:
        stub["attributes"] = attributes
    return stub


def _write_merge_fixture(tmp_path: Path) -> Path:
    """A collection whose stub carries attributes overlapping the target's."""
    (tmp_path / "child.json").write_text(
        json.dumps(
            _collection(
                "child",
                attributes={
                    "shared": "from-target",
                    "targetOnly": 1,
                    "nested": {"k": [1]},
                },
            )
        )
    )
    doc_path = tmp_path / "collection.json"
    doc_path.write_text(
        json.dumps(
            _collection(
                "root",
                _stub(
                    "child",
                    "./child.json",
                    attributes={"shared": "from-stub", "stubOnly": 2},
                ),
            )
        )
    )
    return doc_path


async def test_inline_externalised_fixture_collapses_all_stubs(resolver):
    doc = await resolver.open(str(REFERENCE_DIR / "externalised" / "collection.json"))
    result = await resolver.inline(doc)

    # Two resolution hops collapsed: collection -> child collection -> zarr.
    plate = result.root.nodes[0]
    assert isinstance(plate, ozc.CollectionNode)
    assert plate.path is None
    assert plate.id == "plate-1"

    well = plate.nodes[0]
    assert isinstance(well, ozc.MultiscaleNode)
    assert well.path is None
    # Stub's id/name kept (they match the target's in this fixture).
    assert (well.id, well.name) == ("well-a01", "Well A01")
    assert well.attributes["channel"] == "DAPI"

    # The singlescale's data path survives, rebased against its declaring
    # document (well_a01.zarr/zarr.json) to an absolute path.
    s0 = well.nodes[0]
    assert s0.path is not None
    expected = str(REFERENCE_DIR / "externalised" / "child" / "well_a01.zarr" / "s0")
    assert s0.path.path == expected


async def test_inline_applies_merge_rule_stub_wins(resolver, tmp_path):
    doc = await resolver.open(str(_write_merge_fixture(tmp_path)))
    result = await resolver.inline(doc)

    child = result.root.nodes[0]
    # Union of both sides; the stub wins on conflict (nearer scope).
    assert child.attributes == {
        "shared": "from-stub",
        "targetOnly": 1,
        "stubOnly": 2,
        "nested": {"k": [1]},
    }
    # §5: the merged view keeps the stub's id/name; the path is consumed.
    assert (child.id, child.name) == ("child", "child")
    assert child.path is None
    assert child.nodes == []


async def test_inline_never_mutates_originals(resolver, tmp_path):
    doc = await resolver.open(str(_write_merge_fixture(tmp_path)))
    stub = doc.root.nodes[0]
    result = await resolver.inline(doc)

    # The input tree keeps its stub; the cached target is untouched.
    assert stub.path is not None
    assert stub.nodes is None
    assert stub.attributes == {"shared": "from-stub", "stubOnly": 2}
    target_root = (await resolver.resolve(stub)).root
    assert target_root.attributes == {
        "shared": "from-target",
        "targetOnly": 1,
        "nested": {"k": [1]},
    }

    # Deep mutation of the result never leaks back (no shared nested values).
    child = result.root.nodes[0]
    child.attributes["nested"]["k"].append(2)
    child.attributes["injected"] = True
    result.root.nodes.append("not-a-node")
    assert target_root.attributes["nested"] == {"k": [1]}
    assert "injected" not in target_root.attributes
    assert len(doc.root.nodes) == 1


async def test_inline_data_leaf_skip_and_raise(resolver, tmp_path):
    # Data leaves live in a *child* document, so surviving paths get rebased.
    (tmp_path / "array.zarr").mkdir()
    (tmp_path / "array.zarr" / "zarr.json").write_text(
        json.dumps({"zarr_format": 3, "node_type": "array"})
    )
    (tmp_path / "child.json").write_text(
        json.dumps(
            _collection(
                "child",
                _stub("leaf", "./array.zarr", path_type="zarr"),
                _stub("gone", "./missing.json"),
            )
        )
    )
    doc_path = tmp_path / "collection.json"
    doc_path.write_text(json.dumps(_collection("root", _stub("child", "./child.json"))))
    doc = await resolver.open(str(doc_path))

    result = await resolver.inline(doc)
    leaf, gone = result.root.nodes[0].nodes
    assert leaf.path.path == str(tmp_path / "array.zarr")
    assert isinstance(leaf.path, ozc.ZarrPath)  # no zarr.json suffix appended
    assert gone.path.path == str(tmp_path / "missing.json")

    with pytest.raises((ozc.NotOmeDocumentError, FileNotFoundError)):
        await resolver.inline(doc, on_error="raise")


async def test_inline_top_document_paths_kept_verbatim(resolver, tmp_path):
    (tmp_path / "array.zarr").mkdir()
    (tmp_path / "array.zarr" / "zarr.json").write_text(
        json.dumps({"zarr_format": 3, "node_type": "array"})
    )
    doc_path = tmp_path / "collection.json"
    doc_path.write_text(
        json.dumps(_collection("root", _stub("leaf", "./array.zarr", path_type="zarr")))
    )
    doc = await resolver.open(str(doc_path))

    result = await resolver.inline(doc)
    # Declared in the top document itself: round-trips byte-identically.
    assert result.root.nodes[0].path.path == "./array.zarr"


async def test_inline_cycle_raises(resolver, tmp_path):
    (tmp_path / "a.json").write_text(
        json.dumps(_collection("a", _stub("to-b", "./b.json")))
    )
    (tmp_path / "b.json").write_text(
        json.dumps(_collection("b", _stub("to-a", "./a.json")))
    )

    doc = await resolver.open(str(tmp_path / "a.json"))
    with pytest.raises(ValueError, match="cycle"):
        await resolver.inline(doc)


async def test_inline_diamond_duplicates_subtree(resolver, tmp_path):
    (tmp_path / "shared.json").write_text(json.dumps(_collection("shared")))
    doc_path = tmp_path / "collection.json"
    doc_path.write_text(
        json.dumps(
            _collection(
                "root", _stub("x", "./shared.json"), _stub("y", "./shared.json")
            )
        )
    )

    doc = await resolver.open(str(doc_path))
    result = await resolver.inline(doc)
    # A diamond is not a cycle: the shared target is duplicated, and the
    # stubs' distinct ids keep the merged document collision-free.
    assert [child.id for child in result.root.nodes] == ["x", "y"]
    assert all(child.nodes == [] for child in result.root.nodes)


async def test_inline_duplicate_ids_raise_eagerly(resolver, tmp_path):
    # The shared document's *inner* node id appears twice after inlining.
    (tmp_path / "shared.json").write_text(
        json.dumps(
            _collection(
                "shared",
                {"type": "collection", "id": "inner", "name": "inner", "nodes": []},
            )
        )
    )
    doc_path = tmp_path / "collection.json"
    doc_path.write_text(
        json.dumps(
            _collection(
                "root", _stub("x", "./shared.json"), _stub("y", "./shared.json")
            )
        )
    )

    doc = await resolver.open(str(doc_path))
    with pytest.raises(ValueError, match="duplicate"):
        await resolver.inline(doc)


async def test_inline_roundtrip_serializes_without_metadata_stubs(resolver):
    doc = await resolver.open(str(REFERENCE_DIR / "externalised" / "collection.json"))
    result = await resolver.inline(doc)

    payload = result.serialize_payload()

    def paths(node: dict) -> list[str]:
        found = []
        if "path" in node:
            found.append(node["path"]["path"])
        for child in node.get("nodes", []):
            found.extend(paths(child))
        return found

    # The only surviving path is the data leaf; every metadata stub is gone.
    expected = str(REFERENCE_DIR / "externalised" / "child" / "well_a01.zarr" / "s0")
    assert paths(payload) == [expected]

    # The inlined tree re-validates from its own serialization.
    reparsed = parse_metadata_document(result.serialize_bytes(), url=result.url)
    assert reparsed.root.nodes[0].nodes[0].id == "well-a01"
    assert (result.version, result.form) == (doc.version, doc.form)


async def test_inline_result_provenance_and_cache_isolation(resolver, tmp_path):
    doc = await resolver.open(str(_write_merge_fixture(tmp_path)))
    result = await resolver.inline(doc)

    assert result is not doc
    assert result.root is not doc.root
    assert (result.url, result.form, result.version) == (
        doc.url,
        doc.form,
        doc.version,
    )
    # The result is fully attached to itself (navigable, saveable)...
    assert result.root._document is result
    child = result.root.nodes[0]
    assert child._document is result
    assert child._parent is result.root
    # ...and is a derived artifact: the cache still serves the original.
    assert await resolver.open(doc.url) is doc


async def test_inline_version_from_top_document(resolver, tmp_path):
    child = _collection("child")
    child["ome"]["version"] = "0.y"
    (tmp_path / "child.json").write_text(json.dumps(child))
    doc_path = tmp_path / "collection.json"
    doc_path.write_text(json.dumps(_collection("root", _stub("child", "./child.json"))))

    doc = await resolver.open(str(doc_path))
    result = await resolver.inline(doc)
    assert result.version == "0.x"


async def test_inline_max_depth_zero_is_pure_copy(tmp_path):
    store = CountingStore()
    resolver = ozc.Resolver(store)
    doc = await resolver.open(str(_write_merge_fixture(tmp_path)))

    fetched = store.gets
    result = await resolver.inline(doc, max_depth=0)
    # Nothing resolved: zero fetches, the boundary stub survives with its
    # attributes and top-document path verbatim (no §5 merge).
    assert store.gets == fetched
    stub = result.root.nodes[0]
    assert stub.path.path == "./child.json"
    assert stub.attributes == {"shared": "from-stub", "stubOnly": 2}
    assert stub.nodes is None

    # The partial tree is a real document: it round-trips.
    reparsed = parse_metadata_document(result.serialize_bytes(), url=result.url)
    assert reparsed.root.nodes[0].path.path == "./child.json"


async def test_inline_max_depth_one_keeps_deeper_stubs(tmp_path):
    store = CountingStore()
    resolver = ozc.Resolver(store)
    fixture = REFERENCE_DIR / "externalised" / "collection.json"
    doc = await resolver.open(str(fixture))

    result = await resolver.inline(doc, max_depth=1)
    # First hop collapsed: the plate is embedded, not a stub.
    plate = result.root.nodes[0]
    assert isinstance(plate, ozc.CollectionNode)
    assert plate.path is None
    # Second hop survives as a stub — never fetched, attributes verbatim
    # (the target's channel/coordinateSystems are NOT merged in) — with its
    # path rebased absolute against its declaring (non-top) document.
    well = plate.nodes[0]
    assert isinstance(well, ozc.MultiscaleNode)
    assert well.nodes is None
    assert well.attributes == {}
    expected = str(REFERENCE_DIR / "externalised" / "child" / "well_a01.zarr")
    assert well.path.path == expected
    assert store.gets == 2  # top + child documents; well_a01.zarr untouched

    # The surviving stub's rebased path stays openable.
    target = await resolver.open(well.path.path)
    assert target.root.attributes["channel"] == "DAPI"


async def test_inline_max_depth_cuts_before_cycle(tmp_path):
    (tmp_path / "a.json").write_text(
        json.dumps(_collection("a", _stub("to-b", "./b.json")))
    )
    (tmp_path / "b.json").write_text(
        json.dumps(_collection("b", _stub("to-a", "./a.json")))
    )
    resolver = ozc.Resolver(ozc.LocalStore())
    doc = await resolver.open(str(tmp_path / "a.json"))

    # The b -> a edge sits past the depth boundary, so no cycle is reached.
    result = await resolver.inline(doc, max_depth=1)
    to_a = result.root.nodes[0].nodes[0]
    assert to_a.path.path == str(tmp_path / "a.json")


async def test_inline_is_pure_cache_reads_after_resolve_tree(tmp_path):
    store = CountingStore()
    resolver = ozc.Resolver(store)
    doc = await resolver.open(str(_write_merge_fixture(tmp_path)))
    await resolver.resolve_tree(doc)

    fetched = store.gets
    await resolver.inline(doc)
    assert store.gets == fetched
