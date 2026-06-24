"""Node state (DETACHED / DOCUMENT), the create/save/delete API returning a
typed `RefNode`, bottom-up composition via `add_ref`, and the guard errors that
point each misuse at the right call."""

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
    assert node.nodes[0].state is ngc.NodeState.DETACHED


async def test_inlined_states_are_document(resolver, tmp_path):
    view = await resolver.open_inlined(_stub_fixture(tmp_path))
    assert view.state is ngc.NodeState.DOCUMENT
    child = view.find(id="child")
    assert child.state is ngc.NodeState.DOCUMENT
    # The resolved child is owned by its own document.
    assert child.document_url == str(tmp_path / "child.json")


async def test_added_child_is_detached(resolver, tmp_path):
    root = await resolver.open(_stub_fixture(tmp_path))
    root = root.add(parent_id="root", child=ngc.CollectionNode(id="gc"))
    assert root.find(id="gc").state is ngc.NodeState.DETACHED


# --- create / save return references ----------------------------------------


async def test_create_returns_ref_and_stamps_document(resolver, tmp_path):
    url = str(tmp_path / "collection.json")
    root = ngc.CollectionNode(
        id="root",
        attributes={"a": 1},
        nodes=(ngc.MultiscaleNode(id="img", attributes={"b": 2}),),
    )
    ref = await resolver.create(url, root)

    # The write verbs hand back a typed RefNode stub (decorate-then-add_ref).
    assert isinstance(ref, ngc.RefCollectionNode)
    assert ref.id == "root"
    assert ref.path.path == url
    assert root.state is ngc.NodeState.DOCUMENT  # the passed tree is stamped
    data = json.loads((tmp_path / "collection.json").read_text())["ome"]
    assert data["version"] == "0.x"
    assert data["nodes"][0]["id"] == "img"
    # version is a document-envelope key, never nested into a node.
    assert "version" not in data["nodes"][0]


async def test_create_reopens_equal(resolver, tmp_path):
    url = str(tmp_path / "collection.json")
    await resolver.create(
        url,
        ngc.CollectionNode(
            id="root", nodes=(ngc.MultiscaleNode(id="img", attributes={"b": 2}),)
        ),
    )
    reopened = await ngc.Resolver(ngc.LocalStore()).open(url)
    assert reopened.id == "root"
    assert reopened.find(id="img").attributes == {"b": 2}


async def test_create_then_edit_save_roundtrips(resolver, tmp_path):
    url = str(tmp_path / "collection.json")
    await resolver.create(
        url, ngc.CollectionNode(id="root", nodes=(ngc.MultiscaleNode(id="img"),))
    )
    root = await resolver.open(url)
    root = root.set_attrs(id="img", values={"x": 9})
    ref = await resolver.save(root)
    assert ref.id == "root" and ref.path.path == url

    reopened = await ngc.Resolver(ngc.LocalStore()).open(url)
    assert reopened.find(id="img").attributes["x"] == 9


async def test_create_overwrite_replaces(resolver, tmp_path):
    url = str(tmp_path / "c.json")
    await resolver.create(url, ngc.CollectionNode(id="a"))
    await resolver.create(url, ngc.CollectionNode(id="b"), overwrite=True)
    reopened = await ngc.Resolver(ngc.LocalStore()).open(url)
    assert reopened.id == "b"


# --- bottom-up composition via references -----------------------------------


def _stub(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "collection.json").read_text())["ome"]["nodes"][0]


async def test_compose_via_ref_and_add_ref(resolver, tmp_path):
    """The natural bottom-up flow: parent built detached, written last."""
    # Write the child document first; decorate its returned stub (typed).
    rf_child = await resolver.create(
        str(tmp_path / "child.zarr"),
        ngc.MultiscaleNode(id="img", attributes={"k": 1}),
    )
    assert isinstance(rf_child, ngc.RefMultiscaleNode)
    rf_child = rf_child.set_attrs(id="img", values={"role": "raw"})  # overlay

    # Parent is still detached when add_ref runs; relativization is deferred.
    root = ngc.CollectionNode(id="plate")
    root = root.add_ref(parent_id="plate", ref=rf_child)
    await resolver.create(str(tmp_path / "collection.json"), root)

    # The path is relativized on write; the overlay attribute is stored.
    assert _stub(tmp_path)["path"] == {"type": "zarr", "path": "./child.zarr"}
    assert _stub(tmp_path)["attributes"] == {"role": "raw"}

    # The reference resolves on inline; overlay wins on read.
    view = await ngc.Resolver(ngc.LocalStore()).open_inlined(
        str(tmp_path / "collection.json")
    )
    img = view.find(id="img")
    assert isinstance(img, ngc.InlinedMultiscaleNode)
    assert img.attributes == {"k": 1, "role": "raw"}


async def test_relativize_false_keeps_absolute(resolver, tmp_path):
    rf_child = await resolver.create(
        str(tmp_path / "child.zarr"), ngc.MultiscaleNode(id="img")
    )
    root = ngc.CollectionNode(id="root").add_ref(parent_id="root", ref=rf_child)
    await resolver.create(str(tmp_path / "collection.json"), root, relativize=False)
    # Opted out: the absolute path is stored verbatim.
    assert _stub(tmp_path)["path"]["path"] == str(tmp_path / "child.zarr")


async def test_cross_directory_ref_kept_absolute(resolver, tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    rf_child = await resolver.create(
        str(sub / "child.zarr"), ngc.MultiscaleNode(id="img")
    )
    root = ngc.CollectionNode(id="root").add_ref(parent_id="root", ref=rf_child)
    await resolver.create(str(tmp_path / "collection.json"), root)
    # Different directory cannot be relativized -> kept absolute (best-effort).
    assert _stub(tmp_path)["path"]["path"] == str(sub / "child.zarr")


async def test_node_ref_for_descendant(resolver, tmp_path):
    url = str(tmp_path / "collection.json")
    await resolver.create(
        url, ngc.CollectionNode(id="root", nodes=(ngc.MultiscaleNode(id="img"),))
    )
    root = await resolver.open(url)
    ref = root.find(id="img").ref()
    # An embedded descendant references its container document plus its own id.
    assert ref.id == "img"
    assert ref.path.path == url


def test_ref_on_detached_raises():
    node = ngc.CollectionNode(id="root")
    with pytest.raises(ngc.NodeStateError, match="detached"):
        node.ref()


# --- delete -----------------------------------------------------------------


async def test_delete_embedded_rewrites_keeps_file(resolver, tmp_path):
    url = str(tmp_path / "collection.json")
    await resolver.create(url, ngc.CollectionNode(id="root"))
    root = await resolver.open(url)
    root = root.add(parent_id="root", child=ngc.CollectionNode(id="analysis"))
    await resolver.save(root)

    root = await resolver.open(url)
    deleted = await resolver.delete(root.find(id="analysis"))

    assert deleted == [url]
    assert Path(url).exists()  # file stays; only the node was removed
    reopened = await resolver.open(url)
    assert reopened.find(id="analysis") is None


async def test_delete_root_removes_file(resolver, tmp_path):
    url = str(tmp_path / "child.zarr")
    await resolver.create(url, ngc.MultiscaleNode(id="img"))
    root = await resolver.open(url)

    deleted = await resolver.delete(root)

    assert deleted == [str(tmp_path / "child.zarr" / "zarr.json")]
    assert not (tmp_path / "child.zarr" / "zarr.json").exists()


async def test_delete_detached_raises(resolver):
    with pytest.raises(ngc.NodeStateError, match="detached"):
        await resolver.delete(ngc.CollectionNode(id="root"))


# --- guard errors point to the right API -----------------------------------


async def test_save_on_detached_points_to_create(resolver):
    with pytest.raises(ngc.NodeStateError, match="create"):
        await resolver.save(ngc.CollectionNode(id="root"))


async def test_create_on_persisted_points_to_save(resolver, tmp_path):
    root = await resolver.open(_stub_fixture(tmp_path))
    with pytest.raises(ngc.NodeStateError, match="save"):
        await resolver.create(str(tmp_path / "other.json"), root)


async def test_create_over_existing_raises(resolver, tmp_path):
    url = str(tmp_path / "c.json")
    await resolver.create(url, ngc.CollectionNode(id="a"))
    with pytest.raises(ngc.NodeStateError, match="already exists"):
        await resolver.create(url, ngc.CollectionNode(id="b"))


async def test_add_to_stub_raises(resolver, tmp_path):
    # depth=0 leaves the child as an unresolved reference stub.
    view = await resolver.open_inlined(_stub_fixture(tmp_path), depth=0)
    with pytest.raises(ngc.NodeStateError, match="reference stub"):
        view.add(parent_id="child", child=ngc.CollectionNode(id="gc"))


async def test_add_duplicate_id_raises(resolver, tmp_path):
    root = await resolver.open(_stub_fixture(tmp_path))
    with pytest.raises(ngc.NodeStateError, match="duplicate"):
        root.add(parent_id="root", child=ngc.CollectionNode(id="child"))
