"""Node state (DETACHED / DOCUMENT / BOUNDARY), the `create` API, and the guard
errors that point each misuse at the right call."""

import json
from pathlib import Path

import pytest

import ngio_collections as ngc


@pytest.fixture
def resolver():
    return ngc.Resolver(ngc.LocalStore())


def _stub_fixture(tmp_path: Path) -> str:
    """collection.json with one externalized child.json stub. Returns its path."""
    (tmp_path / "child.json").write_text(
        json.dumps(
            {
                "ome": {
                    "version": "0.x",
                    "type": "collection",
                    "id": "child",
                    "nodes": [],
                }
            }
        )
    )
    (tmp_path / "collection.json").write_text(
        json.dumps(
            {
                "ome": {
                    "version": "0.x",
                    "type": "collection",
                    "id": "root",
                    "nodes": [
                        {
                            "type": "collection",
                            "id": "child",
                            "path": {"type": "json", "path": "./child.json"},
                        }
                    ],
                }
            }
        )
    )
    return str(tmp_path / "collection.json")


# --- state -----------------------------------------------------------------


def test_built_node_is_detached():
    node = ngc.CollectionNode(id="root", nodes=(ngc.MultiscaleNode(id="img"),))
    assert node.is_detached
    assert node.state is ngc.NodeState.DETACHED
    assert not node.is_boundary
    assert node.nodes[0].state is ngc.NodeState.DETACHED


async def test_inlined_states(resolver, tmp_path):
    root = await resolver.inline(_stub_fixture(tmp_path))
    assert root.state is ngc.NodeState.DOCUMENT
    assert not root.is_detached
    child = root.find("child")
    assert child.state is ngc.NodeState.BOUNDARY
    assert child.is_boundary


async def test_added_child_is_detached(resolver, tmp_path):
    root = await resolver.inline(_stub_fixture(tmp_path))
    root = root.add("child", ngc.CollectionNode(id="gc"))
    assert root.find("gc").state is ngc.NodeState.DETACHED
    # The boundary parent keeps its state across the rebuild.
    assert root.find("child").state is ngc.NodeState.BOUNDARY


# --- create ----------------------------------------------------------------


async def test_create_persists_and_stamps_document(resolver, tmp_path):
    url = str(tmp_path / "collection.json")
    root = ngc.CollectionNode(
        id="root",
        attributes={"a": 1},
        nodes=(ngc.MultiscaleNode(id="img", attributes={"b": 2}),),
    )
    saved = await resolver.create(url, root, version="0.x")

    assert saved.state is ngc.NodeState.DOCUMENT
    assert saved.document_url == url
    data = json.loads((tmp_path / "collection.json").read_text())["ome"]
    assert data["version"] == "0.x"
    assert data["id"] == "root"
    assert data["nodes"][0]["id"] == "img"


async def test_create_reopens_equal(resolver, tmp_path):
    url = str(tmp_path / "collection.json")
    await resolver.create(
        url,
        ngc.CollectionNode(
            id="root", nodes=(ngc.MultiscaleNode(id="img", attributes={"b": 2}),)
        ),
        version="0.x",
    )
    reopened = await ngc.Resolver(ngc.LocalStore()).inline(url)
    assert reopened.id == "root"
    assert reopened.find("img").attributes == {"b": 2}


async def test_create_then_edit_save_roundtrips(resolver, tmp_path):
    url = str(tmp_path / "collection.json")
    root = await resolver.create(
        url,
        ngc.CollectionNode(id="root", nodes=(ngc.MultiscaleNode(id="img"),)),
        version="0.x",
    )
    root = root.set_attrs("img", {"x": 9})
    assert await resolver.save(root) == [url]

    reopened = await ngc.Resolver(ngc.LocalStore()).inline(url)
    assert reopened.find("img").attributes["x"] == 9


async def test_bottom_up_composition(resolver, tmp_path):
    # Write the child document first, then the collection that references it.
    await resolver.create(
        str(tmp_path / "child.zarr"),
        ngc.MultiscaleNode(id="img", attributes={"k": 1}),
        version="0.x",
    )
    root = ngc.CollectionNode(
        id="plate",
        nodes=(
            ngc.RefMultiscaleNode(id="img", path=ngc.ZarrPath(path="./child.zarr")),
        ),
    )
    await resolver.create(str(tmp_path / "collection.json"), root, version="0.x")

    reopened = await ngc.Resolver(ngc.LocalStore()).inline(
        str(tmp_path / "collection.json")
    )
    img = reopened.find("img")
    assert img.is_boundary
    assert img.attributes["k"] == 1


async def test_create_overwrite_replaces(resolver, tmp_path):
    url = str(tmp_path / "c.json")
    await resolver.create(url, ngc.CollectionNode(id="a"))
    await resolver.create(url, ngc.CollectionNode(id="b"), overwrite=True)
    reopened = await ngc.Resolver(ngc.LocalStore()).inline(url)
    assert reopened.id == "b"


# --- guard errors point to the right API -----------------------------------


async def test_save_on_detached_points_to_create(resolver, tmp_path):
    root = ngc.CollectionNode(id="root")
    with pytest.raises(ngc.NodeStateError, match="create"):
        await resolver.save(root)


async def test_create_on_persisted_points_to_save(resolver, tmp_path):
    root = await resolver.inline(_stub_fixture(tmp_path))
    with pytest.raises(ngc.NodeStateError, match="save"):
        await resolver.create(str(tmp_path / "other.json"), root)


async def test_create_over_existing_points_to_inline(resolver, tmp_path):
    url = str(tmp_path / "c.json")
    await resolver.create(url, ngc.CollectionNode(id="a"))
    with pytest.raises(ngc.NodeStateError, match="already exists"):
        await resolver.create(url, ngc.CollectionNode(id="b"))


async def test_add_to_stub_points_to_inline(resolver, tmp_path):
    # depth=0 leaves the child as an unresolved reference stub.
    root = await resolver.inline(_stub_fixture(tmp_path), depth=0)
    with pytest.raises(ngc.NodeStateError, match="reference stub"):
        root.add("child", ngc.CollectionNode(id="gc"))


async def test_add_duplicate_id_raises(resolver, tmp_path):
    root = await resolver.inline(_stub_fixture(tmp_path))
    with pytest.raises(ngc.NodeStateError, match="duplicate"):
        root.add("child", ngc.CollectionNode(id="child"))
