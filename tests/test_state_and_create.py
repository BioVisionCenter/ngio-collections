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
                            "name": "child",
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


async def test_inlined_states_are_document(resolver, tmp_path, by_origin):
    view = await resolver.open_inlined(_stub_fixture(tmp_path))
    assert view.state is ngc.NodeState.DOCUMENT
    child = by_origin(view, "child")
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

    # The write verbs hand back a typed, path-based RefNode stub (no id).
    assert isinstance(ref, ngc.RefCollectionNode)
    assert ref.id is None
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
    assert ref.id is None and ref.path.path == url

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


async def test_compose_via_ref_and_add_ref(resolver, tmp_path, by_origin):
    """The natural bottom-up flow: parent built detached, written last."""
    # Write the child document first; decorate its returned stub (typed).
    rf_child = await resolver.create(
        str(tmp_path / "child.zarr"),
        ngc.MultiscaleNode(id="img", attributes={"k": 1}),
    )
    assert isinstance(rf_child, ngc.RefMultiscaleNode)
    assert rf_child.id is None  # path-based stub
    # Decorate the standalone stub with overlay attributes before attaching it.
    rf_child = rf_child.model_copy(update={"attributes": {"role": "raw"}})

    # Parent is still detached when add_ref runs; relativization is deferred.
    root = ngc.CollectionNode(id="plate")
    root = root.add_ref(parent_id="plate", ref=rf_child)
    await resolver.create(str(tmp_path / "collection.json"), root)

    # The path is relativized on write; the overlay attribute is stored.
    assert _stub(tmp_path)["path"] == {"type": "zarr", "path": "./child.zarr"}
    assert _stub(tmp_path)["attributes"] == {"role": "raw"}

    # The reference resolves to the child root on inline; overlay wins on read.
    view = await ngc.Resolver(ngc.LocalStore()).open_inlined(
        str(tmp_path / "collection.json")
    )
    img = by_origin(view, "img")
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


# --- open from a ReferenceObj ------------------------------------------------


async def test_open_from_reference(resolver, tmp_path):
    url = str(tmp_path / "collection.json")
    await resolver.create(
        url, ngc.CollectionNode(id="root", nodes=(ngc.MultiscaleNode(id="img"),))
    )
    ref = (await resolver.open(url)).find(id="img").ref()
    # Opening the locator returns the referenced node directly (no find step).
    node = await resolver.open(ref)
    assert isinstance(node, ngc.MultiscaleNode)
    assert node.id == "img"


async def test_open_inlined_from_reference(resolver, tmp_path):
    url = str(tmp_path / "collection.json")
    await resolver.create(
        url, ngc.CollectionNode(id="root", nodes=(ngc.MultiscaleNode(id="img"),))
    )
    ref = (await resolver.open(url)).find(id="img").ref()
    node = await resolver.open_inlined(ref)
    assert isinstance(node, ngc.InlinedMultiscaleNode)
    # img is embedded in the entry document, so its id stays bare.
    assert node.id == "img"
    assert node._origin_id == "img"


async def test_open_reference_id_not_found_raises(resolver, tmp_path):
    url = str(tmp_path / "collection.json")
    await resolver.create(url, ngc.CollectionNode(id="root"))
    ref = (await resolver.open(url)).ref().model_copy(update={"id": "ghost"})
    with pytest.raises(KeyError, match="ghost"):
        await resolver.open(ref)


async def test_open_same_document_reference_raises(resolver):
    with pytest.raises(ngc.NodeStateError, match="same-document"):
        await resolver.open(ngc.ReferenceObj(id="x"))


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


# --- node-scoped save (splice back into the document) -----------------------


def _nested(tmp_path: Path) -> str:
    return str(tmp_path / "collection.json")


async def _create_nested(resolver, tmp_path) -> str:
    """A `root -> (image, labels -> nuclei)` document; return its url."""
    url = _nested(tmp_path)
    await resolver.create(
        url,
        ngc.CollectionNode(
            id="root",
            nodes=(
                ngc.MultiscaleNode(id="image", name="image"),
                ngc.CollectionNode(
                    id="labels", nodes=(ngc.MultiscaleNode(id="nuclei"),)
                ),
            ),
        ),
    )
    return url


async def test_save_descendant_splices_into_document(resolver, tmp_path):
    url = await _create_nested(resolver, tmp_path)
    # Open just the descendant via its reference, edit it, save it back.
    ref = (await resolver.open(url)).find(id="nuclei").ref()
    nuclei = await resolver.open(ref)
    nuclei = nuclei.set_attrs(id="nuclei", values={"edited": True})
    await resolver.save(nuclei)

    reopened = await resolver.open(url)
    # The edit landed...
    assert reopened.find(id="nuclei").attributes == {"edited": True}
    # ...and every sibling / ancestor survived (no whole-document clobber).
    assert {n.id for n in reopened.walk()} == {"root", "image", "labels", "nuclei"}


async def test_save_root_unchanged_behaviour(resolver, tmp_path):
    url = await _create_nested(resolver, tmp_path)
    root = await resolver.open(url)
    root = root.set_attrs(id="root", values={"touched": 1})
    await resolver.save(root)

    reopened = await resolver.open(url)
    assert reopened.attributes == {"touched": 1}
    assert {n.id for n in reopened.walk()} == {"root", "image", "labels", "nuclei"}


async def test_save_inlined_node_points_to_save_inlined(resolver, tmp_path):
    view = await resolver.open_inlined(_stub_fixture(tmp_path))
    with pytest.raises(ngc.NodeStateError, match="save_inlined"):
        await resolver.save(view)


async def test_save_node_missing_from_document_raises(resolver, tmp_path):
    url = await _create_nested(resolver, tmp_path)
    nuclei = await resolver.open((await resolver.open(url)).find(id="nuclei").ref())
    await resolver.delete(nuclei)  # remove it from disk
    with pytest.raises(ngc.NodeStateError, match="not in document"):
        await resolver.save(nuclei.set_attrs(id="nuclei", values={"x": 1}))


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


def test_add_to_stub_raises():
    # An id-bearing leaf stub cannot receive children: resolve it first.
    root = ngc.CollectionNode(
        id="root",
        nodes=(
            ngc.RefMultiscaleNode(id="s", path=ngc.JsonPath(path="./x.json")),
        ),
    )
    with pytest.raises(ngc.NodeStateError, match="reference stub"):
        root.add(parent_id="s", child=ngc.CollectionNode(id="gc"))


def test_add_duplicate_id_raises():
    root = ngc.CollectionNode(
        id="root", nodes=(ngc.CollectionNode(id="child"),)
    )
    with pytest.raises(ngc.NodeStateError, match="duplicate"):
        root.add(parent_id="root", child=ngc.CollectionNode(id="child"))
