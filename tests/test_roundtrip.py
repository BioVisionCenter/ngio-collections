"""Read with `open` / `open_inlined`, resolve to a document root, overlay, snapshot.

`open` reads one document and leaves cross-document children as `RefNode` stubs.
`open_inlined` resolves each path-based stub by loading its target document and
merging that document's *root* into the stub's position; a stub's attributes
overlay the target on read (stub wins) and node ids are made globally unique as
`<origin_id>-<occurrence_token>` (the entry document stays bare). Tests address
inlined nodes by their pre-namespacing id via the `by_origin` fixture. The
inlined tree is read-only with respect to its origins — edits are functional and
in-memory, and `save_inlined` snapshots the whole resolved tree to one
self-contained file.
"""

import json
import re
from pathlib import Path

import pytest

import ngio_collections as ngc


@pytest.fixture
def resolver():
    return ngc.Resolver(ngc.LocalStore())


def _fixture(tmp_path: Path) -> str:
    """collection.json -> child.json; the stub overlays the target on read.

    The path-based stub (no id) resolves to child.json's root. The stub and
    target share ``shared``; the child also carries custom attributes (including
    a deep custom-prefixed value), to assert graceful round-tripping. Returns the
    collection.json path.
    """
    (tmp_path / "child.json").write_text(
        json.dumps(
            {
                "ome": {
                    "version": "0.x",
                    "type": "collection",
                    "id": "child",
                    "name": "child",
                    "attributes": {
                        "shared": "from-target",
                        "targetOnly": 1,
                        "customField": "keep-me",  # custom attribute
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
                            "name": "child",
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
    child = root.nodes[0]
    assert isinstance(child, ngc.RefNode)
    assert child.id is None  # path-based stub carries no id
    assert child.resolve_path() == str(tmp_path / "child.json")


async def test_open_inlined_resolves_to_document_root(resolver, tmp_path, by_origin):
    view = await resolver.open_inlined(_fixture(tmp_path))
    assert isinstance(view, ngc.InlinedCollectionNode)
    # The stub resolved to child.json's root.
    child = by_origin(view, "child")
    assert isinstance(child, ngc.InlinedCollectionNode)
    # Its id is namespaced with an occurrence token; the origin id is preserved.
    assert re.fullmatch(r"child-[0-9a-f]{8}", child.id) and child._origin_id == "child"
    # The resolved node carries the custom attribute from its own document.
    assert child.attributes["customField"] == "keep-me"


async def test_open_inlined_overlay_stub_wins(resolver, tmp_path, by_origin):
    view = await resolver.open_inlined(_fixture(tmp_path))
    attrs = by_origin(view, "child").attributes
    assert attrs["shared"] == "from-stub"  # stub overlays target (wins)
    assert attrs["targetOnly"] == 1  # from the target
    assert attrs["stubOnly"] == 2  # from the stub
    assert attrs["ngio:custom"] == {"deep": [1]}  # custom attr from target


async def test_stub_resolves_to_root_and_inlines_subtree(
    resolver, tmp_path, by_origin
):
    """A stub resolves to its target document's root; the whole subtree inlines."""
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
                            "type": "collection",  # must match the child root type
                            "name": "child",
                            "path": {"type": "json", "path": "./child.json"},
                        }
                    ],
                }
            }
        )
    )
    view = await resolver.open_inlined(str(tmp_path / "collection.json"))
    # The child root and its whole subtree are inlined.
    assert [n._origin_id for n in view.walk()] == ["root", "child", "leaf"]
    # child and leaf are one occurrence, so they share a token.
    child, leaf = by_origin(view, "child"), by_origin(view, "leaf")
    assert child.id.split("-")[1] == leaf.id.split("-")[1]
    assert isinstance(leaf, ngc.InlinedMultiscaleNode)
    assert leaf.attributes["k"] == 1


async def test_stub_type_mismatch_raises(resolver, tmp_path):
    """A stub whose type differs from the child root's type fails on inline."""
    (tmp_path / "child.json").write_text(
        json.dumps(
            {"ome": {"version": "0.x", "type": "collection", "id": "child"}}
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
                            "type": "multiscale",  # != child root type "collection"
                            "name": "child",
                            "path": {"type": "json", "path": "./child.json"},
                        }
                    ],
                }
            }
        )
    )
    url = str(tmp_path / "collection.json")
    with pytest.raises(TypeError, match="does not match"):
        await resolver.open_inlined(url, on_error="raise")
    # Default skips the mismatch and leaves the stub.
    view = await resolver.open_inlined(url)
    assert isinstance(view.nodes[0], ngc.RefNode)


# --- inlined trees are read-only w.r.t. origins ----------------------------


async def test_inlined_edit_is_functional_no_side_effects(
    resolver, tmp_path, by_origin
):
    view = await resolver.open_inlined(_fixture(tmp_path))
    before = (tmp_path / "child.json").read_bytes()

    child_id = by_origin(view, "child").id
    edited = view.set_attrs(id=child_id, values={"targetOnly": 99})

    assert edited is not view
    assert by_origin(view, "child").attributes["targetOnly"] == 1  # untouched
    assert by_origin(edited, "child").attributes["targetOnly"] == 99
    assert (tmp_path / "child.json").read_bytes() == before  # disk untouched


async def test_inlined_tree_has_no_save(resolver, tmp_path):
    view = await resolver.open_inlined(_fixture(tmp_path))
    # save() is for editable single-document trees; inlined trees only snapshot.
    assert not hasattr(view, "save")


async def test_node_ref_locates_resolved_node(resolver, tmp_path, by_origin):
    view = await resolver.open_inlined(_fixture(tmp_path))
    # The id is namespaced, but ref() yields the node's real on-disk locator.
    ref = by_origin(view, "child").ref()
    assert ref.id == "child"  # origin id, not the namespaced id
    assert ref.path.type == "json"
    assert ref.path.path == str(tmp_path / "child.json")


# --- save_inlined ----------------------------------------------------------


async def test_save_inlined_flattens(resolver, tmp_path, by_origin):
    view = await resolver.open_inlined(_fixture(tmp_path))
    child_id = by_origin(view, "child").id  # the namespaced id
    out = str(tmp_path / "flat.json")
    ref = await resolver.save_inlined(view, out)

    # The returned stub is path-based (no id) and locates the snapshot root.
    assert ref.id is None
    assert ref.path.path == out
    payload = json.loads(Path(out).read_text())["ome"]
    child = payload["nodes"][0]
    assert "path" not in child  # resolved boundary is embedded, not a stub
    assert child["id"] == child_id  # the namespaced id is baked in
    assert child["attributes"]["customField"] == "keep-me"
    assert child["attributes"]["shared"] == "from-stub"  # overlay baked in

    # The snapshot is self-contained: a plain open() needs no further IO.
    reopened = await ngc.Resolver(ngc.LocalStore()).open(out)
    assert reopened.find(id=child_id) is not None
    assert isinstance(reopened.find(id=child_id), ngc.Node)


async def test_save_inlined_no_overwrite(resolver, tmp_path):
    view = await resolver.open_inlined(_fixture(tmp_path))
    out = str(tmp_path / "flat.json")
    await resolver.save_inlined(view, out)
    with pytest.raises(ngc.NodeStateError, match="already exists"):
        await resolver.save_inlined(view, out)


# --- depth / cycles / errors -----------------------------------------------


async def test_depth_zero_leaves_stub(resolver, tmp_path):
    view = await resolver.open_inlined(_fixture(tmp_path), depth=0)
    child = view.nodes[0]
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
                            "name": "b",
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
                            "name": "a",
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
    assert (a._origin_id, b._origin_id, back.id) == ("a", "b", None)
    assert a.id == "a" and re.fullmatch(r"b-[0-9a-f]{8}", b.id)
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
                            "name": "child",
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
    assert isinstance(view.nodes[0], ngc.RefNode)
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
                            "name": "img",
                            "path": {"type": "zarr", "path": "./image.zarr"},
                        }
                    ],
                }
            }
        )
    )
    return str(tmp_path / "collection.json")


async def test_zarr_boundary_inlines_and_refs(resolver, tmp_path, by_origin):
    view = await resolver.open_inlined(_zarr_fixture(tmp_path))
    img = by_origin(view, "img")
    assert isinstance(img, ngc.InlinedMultiscaleNode)
    assert img.attributes["ngio:custom"] == {"deep": [1]}
    # A reference to the resolved node points at the zarr group directory.
    ref = img.ref()
    assert ref.id == "img"  # origin id within image.zarr
    assert ref.path.type == "zarr"
    assert ref.path.path == str(tmp_path / "image.zarr")


# --- id uniqueness ---------------------------------------------------------


def _dup_id_fixture(tmp_path: Path) -> str:
    """One document whose root has two sibling children sharing an id.

    Cross-document / positional collisions get distinct occurrence tokens, so a
    real collision now requires a genuine in-document duplicate: two embedded
    siblings of the entry document, both bare `dup`.
    """
    (tmp_path / "collection.json").write_text(
        json.dumps(
            {
                "ome": {
                    "version": "0.x",
                    "type": "collection",
                    "id": "root",
                    "nodes": [
                        {"type": "collection", "id": "dup", "nodes": []},
                        {"type": "collection", "id": "dup", "nodes": []},
                    ],
                }
            }
        )
    )
    return str(tmp_path / "collection.json")


async def test_duplicate_ids_raise_eagerly(resolver, tmp_path):
    with pytest.raises(ValueError, match="duplicate node id"):
        await resolver.open_inlined(_dup_id_fixture(tmp_path))


async def test_cross_document_ids_are_disambiguated(resolver, tmp_path):
    """Same root id in nested documents namespaces apart by tree path."""
    (tmp_path / "b.json").write_text(
        json.dumps({"ome": {"version": "0.x", "type": "collection", "id": "dup"}})
    )
    (tmp_path / "a.json").write_text(
        json.dumps(
            {
                "ome": {
                    "version": "0.x",
                    "type": "collection",
                    "id": "dup",
                    "nodes": [
                        {
                            "type": "collection",
                            "name": "inner",
                            "path": {"type": "json", "path": "./b.json"},
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
                            "type": "collection",
                            "name": "a",
                            "path": {"type": "json", "path": "./a.json"},
                        }
                    ],
                }
            }
        )
    )
    view = await resolver.open_inlined(str(tmp_path / "collection.json"))
    # Both documents share root id "dup", disambiguated by occurrence token.
    assert [n._origin_id for n in view.walk()] == ["root", "dup", "dup"]
    outer, inner = (n for n in view.walk() if n._origin_id == "dup")
    assert outer.id != inner.id  # distinct namespaced ids
    assert {outer.ref().path.path, inner.ref().path.path} == {
        str(tmp_path / "a.json"),
        str(tmp_path / "b.json"),
    }


async def test_sibling_stubs_same_root_id_no_collision(resolver, tmp_path):
    """Two sibling stubs into documents with the same root id (#5 fixed)."""
    for name in ("a.json", "b.json"):
        (tmp_path / name).write_text(
            json.dumps({"ome": {"version": "0.x", "type": "collection", "id": "dup"}})
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
                            "name": n,
                            "path": {"type": "json", "path": f"./{n}.json"},
                        }
                        for n in ("a", "b")
                    ],
                }
            }
        )
    )
    view = await resolver.open_inlined(str(tmp_path / "collection.json"))
    a, b = view.nodes
    assert a._origin_id == b._origin_id == "dup"  # same on-disk id...
    assert a.id != b.id  # ...distinct after namespacing (different positions)


async def test_same_document_inlined_twice_is_distinct(resolver, tmp_path):
    """Two stubs to the SAME document get distinct ids (different positions)."""
    (tmp_path / "child.json").write_text(
        json.dumps({"ome": {"version": "0.x", "type": "collection", "id": "c"}})
    )
    (tmp_path / "collection.json").write_text(
        json.dumps(
            {
                "ome": {
                    "version": "0.x",
                    "type": "collection",
                    "id": "root",
                    "nodes": [
                        {"type": "collection", "name": n,
                         "path": {"type": "json", "path": "./child.json"}}
                        for n in ("first", "second")
                    ],
                }
            }
        )
    )
    view = await resolver.open_inlined(str(tmp_path / "collection.json"))
    first, second = view.nodes
    assert first._origin_id == second._origin_id == "c"
    assert first.id != second.id


async def test_inlined_id_format(resolver, tmp_path, by_origin):
    """Entry-document ids are bare; inlined ids are `<origin>-<8 hex>`."""
    view = await resolver.open_inlined(_fixture(tmp_path))
    assert view.id == "root"  # entry document: bare
    assert re.fullmatch(r"child-[0-9a-f]{8}", by_origin(view, "child").id)


async def test_inlining_is_deterministic(resolver, tmp_path):
    """Re-inlining the same source yields identical ids."""
    url = _fixture(tmp_path)
    a = await resolver.open_inlined(url)
    b = await ngc.Resolver(ngc.LocalStore()).open_inlined(url)
    assert [n.id for n in a.walk()] == [n.id for n in b.walk()]


async def test_grandparent_ref_resolves_and_inlines(resolver, tmp_path):
    """A `../../` relativized stub round-trips: written relative, resolved back.

    The target group sits two directories above the referencing document, so its
    stub is stored as `../../top.zarr` and must resolve and inline to that root.
    """
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    rf = await resolver.create(str(tmp_path / "top.zarr"), ngc.MultiscaleNode(id="top"))
    root = ngc.CollectionNode(id="root").add_ref(parent_id="root", ref=rf)
    url = str(deep / "collection.json")
    await resolver.create(url, root)

    # Stored relative against the document's directory (two levels up).
    stub = json.loads(Path(url).read_text())["ome"]["nodes"][0]
    assert stub["path"] == {"type": "zarr", "path": "../../top.zarr"}

    # The stub resolves to the absolute target locator (the group dir) and
    # inlines to its root.
    reopened = await ngc.Resolver(ngc.LocalStore()).open(url)
    assert reopened.nodes[0].resolve_path() == str(tmp_path / "top.zarr")
    view = await ngc.Resolver(ngc.LocalStore()).open_inlined(url)
    assert view.nodes[0]._origin_id == "top"
    assert isinstance(view.nodes[0], ngc.InlinedMultiscaleNode)
