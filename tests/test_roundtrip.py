"""Open -> inline -> edit -> write back for v3 (functional, immutable).

v3 never mutates the parsed tree: every edit returns a NEW root and the original
is untouched. Round-trip safety rests on the §5 merge being recorded at inline
time (`merge`) and inverted at save (`split`). These tests verify each edit lands
in the right document, untouched documents stay byte-identical, unknown keys
survive, the source tree is never mutated, and id collisions surface eagerly.
"""

import json
from pathlib import Path

import pytest

import ngio_collections as ngc


@pytest.fixture
def resolver():
    return ngc.Resolver(ngc.LocalStore())


def _fixture(tmp_path: Path) -> Path:
    """A collection.json whose stub annotates an externalized child.json.

    The stub (parent edge) and the target (home) share the ``shared`` key; the
    child also carries an unknown node-level field and a custom attribute, to
    assert graceful round-tripping.
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
    doc_path = tmp_path / "collection.json"
    doc_path.write_text(
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
                            "name": "child",
                            "path": {"type": "json", "path": "./child.json"},
                            "attributes": {"shared": "from-stub", "stubOnly": 2},
                        }
                    ],
                }
            }
        )
    )
    return doc_path


def _stub_attrs(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "collection.json").read_text())["ome"]["nodes"][0][
        "attributes"
    ]


def _stub(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "collection.json").read_text())["ome"]["nodes"][0]


def _child(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "child.json").read_text())["ome"]


def _collection_nodes(tmp_path: Path) -> list:
    return json.loads((tmp_path / "collection.json").read_text())["ome"]["nodes"]


async def test_noop_save_writes_nothing(resolver, tmp_path):
    root = await resolver.inline(str(_fixture(tmp_path)))
    before = (tmp_path / "collection.json").read_bytes()
    before_child = (tmp_path / "child.json").read_bytes()

    assert await resolver.save(root) == []
    # Re-saving an unedited tree leaves every file byte-identical.
    assert (tmp_path / "collection.json").read_bytes() == before
    assert (tmp_path / "child.json").read_bytes() == before_child


async def test_edit_does_not_mutate_source(resolver, tmp_path):
    root = await resolver.inline(str(_fixture(tmp_path)))
    edited = root.set_attrs("child", {"targetOnly": 99})

    # A new tree is returned; the original is value-identical to before.
    assert edited is not root
    assert root.find("child").attributes["targetOnly"] == 1
    assert edited.find("child").attributes["targetOnly"] == 99


async def test_edit_home_attribute_lands_in_target(resolver, tmp_path):
    root = await resolver.inline(str(_fixture(tmp_path)))
    before_collection = (tmp_path / "collection.json").read_bytes()

    root = root.set_attrs("child", {"targetOnly": 99})
    written = await resolver.save(root)

    # Only the home document changed.
    assert written == [str(tmp_path / "child.json")]
    assert _child(tmp_path)["attributes"]["targetOnly"] == 99
    # The parent document is byte-identical and its stub untouched.
    assert (tmp_path / "collection.json").read_bytes() == before_collection
    assert _stub_attrs(tmp_path) == {"shared": "from-stub", "stubOnly": 2}


async def test_edit_edge_attribute_lands_in_parent_target_unchanged(resolver, tmp_path):
    root = await resolver.inline(str(_fixture(tmp_path)))
    before_child = (tmp_path / "child.json").read_bytes()

    # 'shared' originated on the stub (edge); editing it stays on the edge.
    root = root.set_attrs("child", {"shared": "edited"})
    written = await resolver.save(root)

    assert written == [str(tmp_path / "collection.json")]
    assert _stub_attrs(tmp_path)["shared"] == "edited"
    # The target keeps its original (shadowed) value, byte-identical.
    assert (tmp_path / "child.json").read_bytes() == before_child
    assert _child(tmp_path)["attributes"]["shared"] == "from-target"


async def test_new_key_lands_in_home(resolver, tmp_path):
    root = await resolver.inline(str(_fixture(tmp_path)))
    root = root.set_attrs("child", {"brandNew": "x"})
    written = await resolver.save(root)

    assert written == [str(tmp_path / "child.json")]
    assert _child(tmp_path)["attributes"]["brandNew"] == "x"
    assert "brandNew" not in _stub_attrs(tmp_path)


async def test_remove_attribute_drops_from_both_layers(resolver, tmp_path):
    root = await resolver.inline(str(_fixture(tmp_path)))
    # 'shared' is present on both edge and home; deleting it removes both.
    root = root.drop_attrs("child", "shared")
    await resolver.save(root)

    assert "shared" not in _stub_attrs(tmp_path)
    assert "shared" not in _child(tmp_path)["attributes"]


async def test_combined_edit_routes_each_key(resolver, tmp_path):
    """One edit touching an edge key, a home key, and a new key routes each to
    the right document and reopens to the merged view."""
    root = await resolver.inline(str(_fixture(tmp_path)))
    root = root.set_attrs(
        "child", {"shared": "edited", "targetOnly": 42, "brandNew": "z"}
    )
    written = await resolver.save(root)

    assert set(written) == {
        str(tmp_path / "collection.json"),
        str(tmp_path / "child.json"),
    }
    assert _stub_attrs(tmp_path)["shared"] == "edited"  # edge -> parent stub
    assert _child(tmp_path)["attributes"]["targetOnly"] == 42  # home -> target
    assert _child(tmp_path)["attributes"]["brandNew"] == "z"  # new -> home
    assert _child(tmp_path)["attributes"]["shared"] == "from-target"  # shadowed

    reopened = await ngc.Resolver(ngc.LocalStore()).inline(
        str(tmp_path / "collection.json")
    )
    merged = reopened.find("child").attributes
    assert merged["shared"] == "edited"  # stub wins on read
    assert merged["targetOnly"] == 42
    assert merged["brandNew"] == "z"


async def test_rename_boundary_lands_on_stub(resolver, tmp_path):
    root = await resolver.inline(str(_fixture(tmp_path)))
    before_child = (tmp_path / "child.json").read_bytes()

    # A rename edits the reference (the stub); the target keeps its own name.
    root = root.rename("child", "renamed")
    written = await resolver.save(root)

    assert written == [str(tmp_path / "collection.json")]
    assert _stub(tmp_path)["name"] == "renamed"
    assert (tmp_path / "child.json").read_bytes() == before_child
    assert _child(tmp_path)["name"] == "child"


async def test_unknown_fields_round_trip(resolver, tmp_path):
    root = await resolver.inline(str(_fixture(tmp_path)))
    root = root.set_attrs("child", {"targetOnly": 2})  # force a rewrite of child.json
    await resolver.save(root)

    child = _child(tmp_path)
    assert child["customField"] == "keep-me"  # unknown node field survives
    assert child["attributes"]["ngio:custom"] == {"deep": [1]}  # custom attr survives


async def test_add_node_embeds_in_parent_document(resolver, tmp_path):
    root = await resolver.inline(str(_fixture(tmp_path)))
    root = root.add("child", ngc.CollectionNode(id="grandchild", name="gc"))
    written = await resolver.save(root)

    # The added node lands in its parent's home document — no new file.
    assert written == [str(tmp_path / "child.json")]
    nodes = _child(tmp_path)["nodes"]
    assert [n["id"] for n in nodes] == ["grandchild"]
    assert "path" not in nodes[0]
    assert not (tmp_path / "grandchild.json").exists()

    # Re-opening sees the embedded grandchild.
    reopened = await ngc.Resolver(ngc.LocalStore()).inline(
        str(tmp_path / "collection.json")
    )
    assert reopened.find("grandchild") is not None


async def test_remove_unlinks_but_keeps_file(resolver, tmp_path):
    root = await resolver.inline(str(_fixture(tmp_path)))
    root = root.remove("child")  # in-memory unlink only
    written = await resolver.save(root)

    # The parent loses the reference, but the external file stays on disk.
    assert written == [str(tmp_path / "collection.json")]
    assert _collection_nodes(tmp_path) == []
    assert (tmp_path / "child.json").exists()


async def test_delete_subtree_removes_file(resolver, tmp_path):
    root = await resolver.inline(str(_fixture(tmp_path)))
    child = root.find("child")

    # Delete the file(s) first (provenance intact), then unlink in memory.
    deleted = await resolver.delete_subtree(child)
    assert deleted == [str(tmp_path / "child.json")]
    root = root.remove("child")
    await resolver.save(root)

    assert not (tmp_path / "child.json").exists()
    assert _collection_nodes(tmp_path) == []


def _nested_fixture(tmp_path: Path) -> Path:
    """collection.json -> child.json -> grandchild.json (a chain of stubs)."""
    (tmp_path / "grandchild.json").write_text(
        json.dumps(
            {"ome": {"version": "0.x", "type": "collection", "id": "gc", "nodes": []}}
        )
    )
    (tmp_path / "child.json").write_text(
        json.dumps(
            {
                "ome": {
                    "version": "0.x",
                    "type": "collection",
                    "id": "child",
                    "nodes": [
                        {
                            "type": "collection",
                            "id": "gc",
                            "path": {"type": "json", "path": "./grandchild.json"},
                        }
                    ],
                }
            }
        )
    )
    doc_path = tmp_path / "collection.json"
    doc_path.write_text(
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
    return doc_path


async def test_depth_boundary_stub_round_trips(resolver, tmp_path):
    # depth=1 inlines only the root's own stub (child); grandchild stays a stub.
    root = await resolver.inline(str(_nested_fixture(tmp_path)), depth=1)
    before = {
        name: (tmp_path / name).read_bytes()
        for name in ("collection.json", "child.json", "grandchild.json")
    }
    # The un-inlined deeper stub re-emits verbatim — nothing is rewritten.
    assert await resolver.save(root) == []
    for name, data in before.items():
        assert (tmp_path / name).read_bytes() == data


def _zarr_fixture(tmp_path: Path) -> Path:
    """collection.json -> image.zarr/zarr.json (a Zarr-group boundary target).

    The Zarr document keeps the OME payload under ``attributes.ome`` and carries
    sibling top-level keys (``zarr_format`` / ``node_type``) plus a sibling
    attribute, to assert the Zarr write-back preserves the group wrapper and does
    not hoist ``ome`` to the top level.
    """
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
    doc_path = tmp_path / "collection.json"
    doc_path.write_text(
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
    return doc_path


def _zarr_doc(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "image.zarr" / "zarr.json").read_text())


async def test_zarr_boundary_noop_save_writes_nothing(resolver, tmp_path):
    # Re-saving an unedited tree with a Zarr-group boundary must leave every file
    # byte-identical (the Zarr write-back must not hoist `ome` out of attributes).
    root = await resolver.inline(str(_zarr_fixture(tmp_path)))
    before = (tmp_path / "collection.json").read_bytes()
    before_zarr = (tmp_path / "image.zarr" / "zarr.json").read_bytes()

    assert await resolver.save(root) == []
    assert (tmp_path / "collection.json").read_bytes() == before
    assert (tmp_path / "image.zarr" / "zarr.json").read_bytes() == before_zarr


async def test_zarr_boundary_edit_keeps_group_wrapper(resolver, tmp_path):
    root = await resolver.inline(str(_zarr_fixture(tmp_path)))
    root = root.set_attrs("img", {"ngio:custom": {"deep": [2]}})
    written = await resolver.save(root)

    assert written == [str(tmp_path / "image.zarr" / "zarr.json")]
    doc = _zarr_doc(tmp_path)
    # The OME payload stays under attributes.ome (not hoisted to the top level),
    # and the group / sibling keys survive untouched.
    assert "ome" not in doc
    assert doc["zarr_format"] == 3 and doc["node_type"] == "group"
    assert doc["attributes"]["sibling"] == "keep-me"
    assert doc["attributes"]["ome"]["attributes"]["ngio:custom"] == {"deep": [2]}


def _dup_id_fixture(tmp_path: Path) -> Path:
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
    doc_path = tmp_path / "collection.json"
    doc_path.write_text(
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
    return doc_path


async def test_duplicate_ids_raise_eagerly(resolver, tmp_path):
    with pytest.raises(ValueError, match="duplicate node id"):
        await resolver.inline(str(_dup_id_fixture(tmp_path)))
