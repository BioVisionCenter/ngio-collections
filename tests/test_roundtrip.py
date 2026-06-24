"""Read with `open` / `open_inlined`, resolve by id, overlay on read, snapshot.

`open` reads one document and leaves cross-document children as `RefNode` stubs.
`open_inlined` resolves each stub by loading its target document and finding the
referenced node *by id* inside it; a stub's attributes overlay the target on read
(stub wins). The inlined tree is read-only with respect to its origins — edits
are functional and in-memory, and `save_inlined` snapshots the whole resolved
tree to one self-contained file.
"""

import json
from pathlib import Path

import pytest

import ngio_collections as ngc


@pytest.fixture
def resolver():
    return ngc.Resolver(ngc.LocalStore())


def _fixture(tmp_path: Path) -> str:
    """collection.json -> child.json; the stub overlays the target on read.

    The stub references the child by the id it carries inside its own document
    (``child``). The stub and target share ``shared``; the child also carries an
    unknown node-level field and a custom attribute, to assert graceful
    round-tripping. Returns the collection.json path.
    """
    (tmp_path / "child.json").write_text(
        json.dumps(
            {
                "ome": {
                    "version": "0.x",
                    "type": "collection",
                    "id": "child",
                    "name": "child",
                    "customField": "keep-me",  # unknown node-level field
                    "attributes": {
                        "shared": "from-target",
                        "targetOnly": 1,
                        "ngio:custom": {"deep": [1]},
                    },
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
                    "name": "root",
                    "nodes": [
                        {
                            "type": "collection",
                            "id": "child",
                            "path": {"type": "json", "path": "./child.json"},
                            "attributes": {"shared": "from-stub", "stubOnly": 2},
                        }
                    ],
                }
            }
        )
    )
    return str(tmp_path / "collection.json")


# --- open vs open_inlined --------------------------------------------------


async def test_open_leaves_stubs(resolver, tmp_path):
    root = await resolver.open(_fixture(tmp_path))
    assert isinstance(root, ngc.CollectionNode)
    child = root.find(id="child")
    assert isinstance(child, ngc.RefNode)
    assert child.resolve_path() == str(tmp_path / "child.json")


async def test_open_inlined_resolves_by_id(resolver, tmp_path):
    view = await resolver.open_inlined(_fixture(tmp_path))
    assert isinstance(view, ngc.InlinedCollectionNode)
    child = view.find(id="child")
    assert isinstance(child, ngc.InlinedCollectionNode)
    # The resolved node carries the unknown field from its own document.
    assert getattr(child, "customField") == "keep-me"


async def test_open_inlined_overlay_stub_wins(resolver, tmp_path):
    view = await resolver.open_inlined(_fixture(tmp_path))
    attrs = view.find(id="child").attributes
    assert attrs["shared"] == "from-stub"  # stub overlays target (wins)
    assert attrs["targetOnly"] == 1  # from the target
    assert attrs["stubOnly"] == 2  # from the stub
    assert attrs["ngio:custom"] == {"deep": [1]}  # custom attr from target


async def test_resolve_descendant_by_id(resolver, tmp_path):
    """A reference may locate a non-root descendant by id within a document."""
    (tmp_path / "child.json").write_text(
        json.dumps(
            {
                "ome": {
                    "version": "0.x",
                    "type": "collection",
                    "id": "child",
                    "nodes": [
                        {
                            "type": "multiscale",
                            "id": "leaf",
                            "attributes": {"k": 1},
                            "nodes": [],
                        }
                    ],
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
                            "type": "multiscale",
                            "id": "leaf",
                            "path": {"type": "json", "path": "./child.json"},
                        }
                    ],
                }
            }
        )
    )
    view = await resolver.open_inlined(str(tmp_path / "collection.json"))
    # Only the addressed subtree is spliced in; the surrounding "child" is not.
    assert [n.id for n in view.walk()] == ["root", "leaf"]
    leaf = view.find(id="leaf")
    assert isinstance(leaf, ngc.InlinedMultiscaleNode)
    assert leaf.attributes["k"] == 1


# --- inlined trees are read-only w.r.t. origins ----------------------------


async def test_inlined_edit_is_functional_no_side_effects(resolver, tmp_path):
    view = await resolver.open_inlined(_fixture(tmp_path))
    before = (tmp_path / "child.json").read_bytes()

    edited = view.set_attrs(id="child", values={"targetOnly": 99})

    assert edited is not view
    assert view.find(id="child").attributes["targetOnly"] == 1  # source untouched
    assert edited.find(id="child").attributes["targetOnly"] == 99
    assert (tmp_path / "child.json").read_bytes() == before  # disk untouched


async def test_inlined_tree_has_no_save(resolver, tmp_path):
    view = await resolver.open_inlined(_fixture(tmp_path))
    # save() is for editable single-document trees; inlined trees only snapshot.
    assert not hasattr(view, "save")


async def test_node_ref_locates_resolved_node(resolver, tmp_path):
    view = await resolver.open_inlined(_fixture(tmp_path))
    ref = view.find(id="child").ref()
    assert ref.id == "child"
    assert ref.path.type == "json"
    assert ref.path.path == str(tmp_path / "child.json")


# --- save_inlined ----------------------------------------------------------


async def test_save_inlined_flattens(resolver, tmp_path):
    view = await resolver.open_inlined(_fixture(tmp_path))
    out = str(tmp_path / "flat.json")
    ref = await resolver.save_inlined(view, out)

    assert ref.id == "root"
    payload = json.loads(Path(out).read_text())["ome"]
    child = payload["nodes"][0]
    assert "path" not in child  # resolved boundary is embedded, not a stub
    assert child["id"] == "child"
    assert child["customField"] == "keep-me"
    assert child["attributes"]["shared"] == "from-stub"  # overlay baked in

    # The snapshot is self-contained: a plain open() needs no further IO.
    reopened = await ngc.Resolver(ngc.LocalStore()).open(out)
    assert reopened.find(id="child") is not None
    assert isinstance(reopened.find(id="child"), ngc.Node)


async def test_save_inlined_no_overwrite(resolver, tmp_path):
    view = await resolver.open_inlined(_fixture(tmp_path))
    out = str(tmp_path / "flat.json")
    await resolver.save_inlined(view, out)
    with pytest.raises(ngc.NodeStateError, match="already exists"):
        await resolver.save_inlined(view, out)


# --- depth / cycles / errors -----------------------------------------------


async def test_depth_zero_leaves_stub(resolver, tmp_path):
    view = await resolver.open_inlined(_fixture(tmp_path), depth=0)
    child = view.find(id="child")
    assert isinstance(child, ngc.RefNode)  # un-inlined: stays a stub


def _cycle_fixture(tmp_path: Path) -> str:
    """a.json -> b.json -> a.json (a document cycle)."""
    (tmp_path / "a.json").write_text(
        json.dumps(
            {
                "ome": {
                    "version": "0.x",
                    "type": "collection",
                    "id": "a",
                    "nodes": [
                        {
                            "type": "collection",
                            "id": "b",
                            "path": {"type": "json", "path": "./b.json"},
                        }
                    ],
                }
            }
        )
    )
    (tmp_path / "b.json").write_text(
        json.dumps(
            {
                "ome": {
                    "version": "0.x",
                    "type": "collection",
                    "id": "b",
                    "nodes": [
                        {
                            "type": "collection",
                            "id": "a",
                            "path": {"type": "json", "path": "./a.json"},
                        }
                    ],
                }
            }
        )
    )
    return str(tmp_path / "a.json")


async def test_cycle_left_as_stub(resolver, tmp_path):
    view = await resolver.open_inlined(_cycle_fixture(tmp_path))
    a, b, back = list(view.walk())
    assert (a.id, b.id, back.id) == ("a", "b", "a")
    assert isinstance(b, ngc.InlinedCollectionNode)
    assert isinstance(back, ngc.RefNode)  # the cycle hop stays a stub


async def test_missing_target_raises_when_asked(resolver, tmp_path):
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
                            "path": {"type": "json", "path": "./missing.json"},
                        }
                    ],
                }
            }
        )
    )
    url = str(tmp_path / "collection.json")
    # Default skips the unreadable target...
    view = await resolver.open_inlined(url)
    assert isinstance(view.find(id="child"), ngc.RefNode)
    # ...but on_error="raise" propagates.
    with pytest.raises(Exception):
        await ngc.Resolver(ngc.LocalStore()).open_inlined(url, on_error="raise")


# --- zarr-group boundary ---------------------------------------------------


def _zarr_fixture(tmp_path: Path) -> str:
    """collection.json -> image.zarr/zarr.json (a Zarr-group boundary target)."""
    image = tmp_path / "image.zarr"
    image.mkdir()
    (image / "zarr.json").write_text(
        json.dumps(
            {
                "zarr_format": 3,
                "node_type": "group",
                "attributes": {
                    "ome": {
                        "version": "0.x",
                        "type": "multiscale",
                        "id": "img",
                        "name": "img",
                        "attributes": {"ngio:custom": {"deep": [1]}},
                        "nodes": [],
                    },
                    "sibling": "keep-me",
                },
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
                            "type": "multiscale",
                            "id": "img",
                            "path": {"type": "zarr", "path": "./image.zarr"},
                        }
                    ],
                }
            }
        )
    )
    return str(tmp_path / "collection.json")


async def test_zarr_boundary_inlines_and_refs(resolver, tmp_path):
    view = await resolver.open_inlined(_zarr_fixture(tmp_path))
    img = view.find(id="img")
    assert isinstance(img, ngc.InlinedMultiscaleNode)
    assert img.attributes["ngio:custom"] == {"deep": [1]}
    # A reference to the resolved node points at the zarr group directory.
    ref = img.ref()
    assert ref.path.type == "zarr"
    assert ref.path.path == str(tmp_path / "image.zarr")


# --- id uniqueness ---------------------------------------------------------


def _dup_id_fixture(tmp_path: Path) -> str:
    """child.json embeds a node whose id collides with the top root's id."""
    (tmp_path / "child.json").write_text(
        json.dumps(
            {
                "ome": {
                    "version": "0.x",
                    "type": "collection",
                    "id": "child",
                    "nodes": [{"type": "collection", "id": "root", "nodes": []}],
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


async def test_duplicate_ids_raise_eagerly(resolver, tmp_path):
    with pytest.raises(ValueError, match="duplicate node id"):
        await resolver.open_inlined(_dup_id_fixture(tmp_path))
