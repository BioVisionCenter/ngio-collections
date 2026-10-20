"""Property tests for the graph core (NodeTree / NodeRecord / PersistentMap).

These exercise the layer in isolation: immutability and structural sharing,
index lookups (ids and nested declarations), positional identity (no id
rewriting), and the shape invariant, independent of any IO.
"""

from __future__ import annotations

import pytest

from ngio_collections.graph import (
    ROOT,
    NodeRecord,
    NodeTree,
    PersistentMap,
    TreeBuilder,
    declared_ids,
    find_declaration,
    merge_traits,
    traits_from_list,
    traits_to_list,
)
from ngio_collections.models._paths import ZarrPath
from tests.conftest import mk

WELL = {"type": "well", "row_index": 0, "column_index": 0}
SCENE = {
    "type": "scene",
    "coordinate_systems": [{"type": "coordinate_system", "id": mk(0x5), "axes": []}],
}
SCALES = {
    "scales": [
        {
            "type": "scale",
            "id": mk(0xC),
            "path": {"type": "zarr", "format": "relative", "href": "./s0"},
        }
    ]
}


# --------------------------------------------------------------------------- #
# PersistentMap
# --------------------------------------------------------------------------- #


def test_pmap_set_is_immutable() -> None:
    a = PersistentMap({"x": 1})
    b = a.set("y", 2)
    assert "y" not in a and a["x"] == 1
    assert b["x"] == 1 and b["y"] == 2


def test_pmap_evolver_batches_then_finishes_once() -> None:
    base = PersistentMap({"x": 1})
    ev = base.mutate()
    ev.set("y", 2).set("z", 3).delete("x")
    out = ev.finish()
    assert base["x"] == 1 and len(base) == 1
    assert dict(out.items()) == {"y": 2, "z": 3}
    with pytest.raises(RuntimeError):
        ev.finish()


# --------------------------------------------------------------------------- #
# NodeRecord shape invariant and trait helpers
# --------------------------------------------------------------------------- #


def test_record_rejects_branch_and_path_together() -> None:
    with pytest.raises(ValueError):
        NodeRecord(type="collection", id=mk(1), children=(), path=ZarrPath(href="../x"))


def test_record_requires_an_id() -> None:
    with pytest.raises(ValueError):
        NodeRecord(type="collection", id="")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        NodeRecord(type="collection", id=None)  # type: ignore[arg-type]


def test_record_shapes() -> None:
    branch = NodeRecord(type="collection", id=mk(1), children=())
    leaf = NodeRecord(type="collection", id=mk(2))
    external = NodeRecord(
        type="multiscale", id=mk(3), path=ZarrPath(href="../image.zarr")
    )
    assert branch.is_branch and not branch.is_external
    assert leaf.is_leaf
    assert external.is_external and not external.is_branch


def test_record_checks_the_trait_index() -> None:
    with pytest.raises(ValueError):
        NodeRecord(type="collection", id=mk(1), traits={"plate": WELL})


def test_traits_from_list_indexes_by_type_and_rejects_duplicates() -> None:
    traits = traits_from_list([WELL, SCENE])
    assert list(traits) == ["well", "scene"] and traits["well"] is WELL
    assert traits_to_list(traits) == [WELL, SCENE]
    with pytest.raises(ValueError):
        traits_from_list([WELL, {"type": "well", "row_index": 1, "column_index": 1}])
    assert list(
        traits_from_list([WELL, {**WELL, "row_index": 9}], on_duplicate="last")[
            "well"
        ].items()
    )[1] == ("row_index", 9)
    with pytest.raises(ValueError):
        traits_from_list([{"row_index": 0}])  # no type


def test_merge_traits_override_wins_per_type_and_keeps_order() -> None:
    base = traits_from_list([WELL, SCENE])
    override = traits_from_list(
        [{"type": "scene", "coordinate_systems": []}, {"type": "labels"}]
    )
    merged = merge_traits(base, override)
    assert list(merged) == ["well", "scene", "labels"]
    assert merged["scene"] == {"type": "scene", "coordinate_systems": []}
    assert merged["well"] is WELL
    assert merge_traits(base, {}) is base


def test_declarations_nested_in_fields_and_traits() -> None:
    record = NodeRecord(
        type="multiscale", id=mk(1), traits={"scene": SCENE}, fields=SCALES
    )
    assert set(declared_ids(record)) == {mk(0xC), mk(0x5)}
    assert find_declaration(record, mk(0xC))["type"] == "scale"
    assert find_declaration(record, mk(0x99)) is None
    # references ({type, ref}) are not declarations
    ref_only = NodeRecord(
        type="collection",
        id=mk(2),
        traits={
            "labels": {
                "type": "labels",
                "source": [{"type": "multiscale", "ref": mk(1)}],
            }
        },
    )
    assert declared_ids(ref_only) == ()


# --------------------------------------------------------------------------- #
# NodeTree construction, navigation, indices
# --------------------------------------------------------------------------- #


def _sample() -> tuple[NodeTree, dict[str, tuple[str, ...]]]:
    """root → {img (external), labels → nuclei}; returns the tree and key map."""
    c = NodeTree.of(NodeRecord(type="collection", id=mk(0), name="root", children=()))
    c, img = c.add_child(
        ROOT,
        NodeRecord(type="multiscale", id=mk(1), path=ZarrPath(href="./img"), fields={}),
    )
    c, labels = c.add_child(
        ROOT, NodeRecord(type="collection", id=mk(2), name="labels", children=())
    )
    c, nuclei = c.add_child(
        labels,
        NodeRecord(type="multiscale", id=mk(3), traits={"scene": SCENE}, fields=SCALES),
    )
    return c, {"root": ROOT, "img": img, "labels": labels, "nuclei": nuclei}


def test_walk_find_parent_children() -> None:
    c, k = _sample()
    assert list(c.walk()) == [k["root"], k["img"], k["labels"], k["nuclei"]]
    assert c.find(mk(3)) == (k["nuclei"],)
    assert c.parent_id(k["nuclei"]) == k["labels"]
    assert c.children_ids(k["root"]) == (k["img"], k["labels"])
    assert c.find(mk(99)) == ()


def test_keys_encode_path_from_ids() -> None:
    c, k = _sample()
    assert k["nuclei"] == (mk(2), mk(3))
    assert c.record(k["nuclei"]).id == mk(3)


def test_declaration_index_follows_edits() -> None:
    c, k = _sample()
    assert c.declarations(mk(0xC)) == (k["nuclei"],)
    assert c.declarations(mk(0x5)) == (k["nuclei"],)
    c2 = c.drop_traits(k["nuclei"], ("scene",))
    assert c2.declarations(mk(0x5)) == () and c2.declarations(mk(0xC)) == (k["nuclei"],)
    c3 = c2.set_fields(k["nuclei"], {})
    assert c3.declarations(mk(0xC)) == ()
    c4 = c3.set_trait(k["nuclei"], SCENE)
    assert c4.declarations(mk(0x5)) == (k["nuclei"],)
    assert c.declarations(mk(0x5)) == (k["nuclei"],)  # original untouched


def test_edit_returns_new_tree_and_shares_untouched_records() -> None:
    c, k = _sample()
    c2 = c.set_trait(k["labels"], WELL)
    assert "well" not in c.record(k["labels"]).traits
    assert c2.record(k["labels"]).traits["well"] == WELL
    assert c2.record(k["nuclei"]) is c.record(k["nuclei"])
    assert c2.record(k["img"]) is c.record(k["img"])


def test_set_traits_replaces_and_rename() -> None:
    c, k = _sample()
    c = c.set_traits(k["nuclei"], {"well": WELL})
    assert list(c.record(k["nuclei"]).traits) == ["well"]
    c = c.rename(k["nuclei"], "Nuclei")
    assert c.record(k["nuclei"]).name == "Nuclei"
    with pytest.raises(ValueError):
        c.set_trait(k["nuclei"], {"row_index": 1})  # no type


def test_cannot_add_under_external_node() -> None:
    c, k = _sample()
    with pytest.raises(ValueError):
        c.add_child(k["img"], NodeRecord(type="collection", id=mk(9)))


def test_same_id_under_two_parents_yields_distinct_keys() -> None:
    c, k = _sample()
    c, a = c.add_child(k["labels"], NodeRecord(type="collection", id=mk(7)))
    c, b = c.add_child(k["root"], NodeRecord(type="collection", id=mk(7)))
    assert a != b and set(c.find(mk(7))) == {a, b}
    assert c.record(a).id == c.record(b).id == mk(7)


def test_duplicate_id_among_siblings_falls_back_to_positional_segment() -> None:
    c = NodeTree.of(NodeRecord(type="collection", id=mk(0), children=()))
    c, first = c.add_child(ROOT, NodeRecord(type="collection", id=mk(1)))
    c, second = c.add_child(ROOT, NodeRecord(type="collection", id=mk(1)))
    assert first == (mk(1),) and second != first
    assert set(c.find(mk(1))) == {first, second}


def test_remove_subtree_updates_nodes_and_indices() -> None:
    c, k = _sample()
    c2 = c.remove(k["labels"])
    assert k["labels"] not in c2 and k["nuclei"] not in c2
    assert c2.find(mk(3)) == () and c2.declarations(mk(0xC)) == ()
    assert c2.children_ids(ROOT) == (k["img"],)
    assert k["nuclei"] in c
    with pytest.raises(ValueError):
        c.remove(ROOT)
    assert c.remove(("does", "not", "exist")) is c


def test_replace_swaps_subtree_keeping_key_and_position() -> None:
    c, k = _sample()
    stub = NodeRecord(type="collection", id=mk(2), path=ZarrPath(href="/labels.zarr"))
    c2 = c.replace(k["labels"], stub)
    assert c2.children_ids(ROOT) == (k["img"], k["labels"])
    assert c2.record(k["labels"]).is_external
    assert (
        k["nuclei"] not in c2
        and c2.find(mk(3)) == ()
        and c2.declarations(mk(0xC)) == ()
    )
    assert c2.find(mk(2)) == (k["labels"],)
    with pytest.raises(KeyError):
        c.replace(("absent",), NodeRecord(type="collection", id=mk(8)))


def test_tree_builder_matches_incremental_add_child_and_carries_manifests() -> None:
    manifests = {"/data/zarr.json": ({"id": "https://x.org/", "version": "1"},)}
    tb = TreeBuilder(
        NodeRecord(type="collection", id=mk(0), children=()), manifests=manifests
    )
    tb.add_child(
        ROOT,
        NodeRecord(type="multiscale", id=mk(1), path=ZarrPath(href="./img"), fields={}),
    )
    labels = tb.add_child(
        ROOT, NodeRecord(type="collection", id=mk(2), name="labels", children=())
    )
    tb.add_child(
        labels,
        NodeRecord(type="multiscale", id=mk(3), traits={"scene": SCENE}, fields=SCALES),
    )
    built = tb.finish()
    inc, _ = _sample()
    assert [built.record(n).id for n in built.walk()] == [
        inc.record(n).id for n in inc.walk()
    ]
    assert built.declarations(mk(0xC)) == inc.declarations(mk(0xC))
    assert built.manifests == manifests
    with pytest.raises(RuntimeError):
        tb.finish()
