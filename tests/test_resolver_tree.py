"""Resolver.resolve_tree(): breadth-first cache warming over a whole
collection, with data-leaf skipping (DESIGN.md §5)."""

import json
from pathlib import Path

import pytest

import ngio_collections as ngc

REFERENCE_DIR = Path(__file__).parent / "data"


class CountingStore(ngc.LocalStore):
    """LocalStore that counts get() calls, to assert cache hits."""

    def __init__(self):
        self.gets = 0

    async def get(self, url: str) -> bytes:
        self.gets += 1
        return await super().get(url)


@pytest.fixture
def resolver():
    return ngc.Resolver(ngc.LocalStore())


def _collection(node_id: str, *nodes: dict) -> dict:
    return {
        "ome": {
            "version": "0.x",
            "type": "collection",
            "id": node_id,
            "name": node_id,
            "nodes": list(nodes),
        }
    }


def _stub(node_id: str, path: str, *, path_type: str = "json") -> dict:
    return {
        "type": "collection",
        "id": node_id,
        "name": node_id,
        "path": {"type": path_type, "path": path},
    }


async def test_resolve_tree_reaches_every_document(resolver):
    doc = await resolver.open(str(REFERENCE_DIR / "externalised" / "collection.json"))
    documents = await resolver.resolve_tree(doc)

    assert documents[0] is doc
    assert [d.url.rsplit("externalised/", 1)[1] for d in documents] == [
        "collection.json",
        "child/collection.json",
        "child/well_a01.zarr/zarr.json",
    ]
    # Each returned document IS the cached instance the stubs resolve to.
    child = documents[1]
    assert await resolver.resolve(doc.root.nodes[0]) is child
    assert await resolver.resolve(child.root.nodes[0]) is documents[2]
    # The parsed trees keep their stubs in place (DESIGN.md §3.3).
    assert doc.root.nodes[0].path is not None
    assert doc.root.nodes[0].nodes is None


async def test_resolve_tree_warms_cache():
    store = CountingStore()
    resolver = ngc.Resolver(store)
    doc = await resolver.open(str(REFERENCE_DIR / "externalised" / "collection.json"))
    await resolver.resolve_tree(doc)

    # Navigation over the warmed tree fetches nothing further.
    fetched = store.gets
    plate = (await resolver.children(doc.root))[0]
    well = (await resolver.children(plate))[0]
    assert well.attributes["channel"] == "DAPI"
    assert store.gets == fetched


async def test_resolve_tree_skips_missing_data_leaf(resolver):
    # well_a01.zarr's singlescale points at ./s0, which does not exist.
    doc = await resolver.open(str(REFERENCE_DIR / "externalised" / "collection.json"))
    documents = await resolver.resolve_tree(doc)
    assert len(documents) == 3

    with pytest.raises(FileNotFoundError):
        await resolver.resolve_tree(doc, on_error="raise")


async def test_resolve_tree_skips_plain_zarr_target(resolver, tmp_path):
    # A stub whose target zarr.json has no `ome` key is a data leaf.
    (tmp_path / "array.zarr").mkdir()
    (tmp_path / "array.zarr" / "zarr.json").write_text(
        json.dumps({"zarr_format": 3, "node_type": "array"})
    )
    root_path = tmp_path / "collection.json"
    root_path.write_text(
        json.dumps(_collection("root", _stub("a", "./array.zarr", path_type="zarr")))
    )

    doc = await resolver.open(str(root_path))
    documents = await resolver.resolve_tree(doc)
    assert documents == [doc]

    with pytest.raises(ngc.NotOmeDocumentError):
        await resolver.resolve_tree(doc, on_error="raise")


async def test_resolve_tree_raises_on_malformed_target_even_when_skipping(
    resolver, tmp_path
):
    (tmp_path / "broken.json").write_text("{not json")
    root_path = tmp_path / "collection.json"
    root_path.write_text(json.dumps(_collection("root", _stub("a", "./broken.json"))))

    doc = await resolver.open(str(root_path))
    with pytest.raises(json.JSONDecodeError):
        await resolver.resolve_tree(doc)  # on_error="skip" only covers data leaves


async def test_resolve_tree_max_depth():
    url = str(REFERENCE_DIR / "externalised" / "collection.json")

    store = CountingStore()
    resolver = ngc.Resolver(store)
    doc = await resolver.open(url)
    assert await resolver.resolve_tree(doc, max_depth=0) == [doc]
    assert store.gets == 1  # only the open() itself

    assert len(await resolver.resolve_tree(doc, max_depth=1)) == 2
    assert len(await resolver.resolve_tree(doc, max_depth=2)) == 3


async def test_resolve_tree_terminates_on_cycles(resolver, tmp_path):
    (tmp_path / "a.json").write_text(
        json.dumps(_collection("a", _stub("to-b", "./b.json")))
    )
    (tmp_path / "b.json").write_text(
        json.dumps(_collection("b", _stub("to-a", "./a.json")))
    )

    doc = await resolver.open(str(tmp_path / "a.json"))
    documents = await resolver.resolve_tree(doc)
    assert [d.root.id for d in documents] == ["a", "b"]


async def test_resolve_tree_dedupes_shared_target(tmp_path):
    (tmp_path / "shared.json").write_text(json.dumps(_collection("shared")))
    root_path = tmp_path / "collection.json"
    root_path.write_text(
        json.dumps(
            _collection(
                "root", _stub("x", "./shared.json"), _stub("y", "./shared.json")
            )
        )
    )

    store = CountingStore()
    resolver = ngc.Resolver(store)
    doc = await resolver.open(str(root_path))
    documents = await resolver.resolve_tree(doc)

    assert [d.root.id for d in documents] == ["root", "shared"]
    assert store.gets == 2  # root + one fetch of the shared target
