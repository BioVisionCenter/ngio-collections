"""Property tests for the v5 graph core (NodeTree / NodeRecord / PersistentMap).

These exercise the L2 layer in isolation: immutability and structural sharing,
O(1)-style find via the indices, positional identity (no id rewriting), and the
shape invariant — independent of any IO.
"""

from __future__ import annotations

import pytest

from ngio_collections.graph import (
    ROOT,
    NodeRecord,
    NodeTree,
    PersistentMap,
    Reference,
    TreeBuilder,
)
from ngio_collections.models._paths import ZarrPath


# --------------------------------------------------------------------------- #
# PersistentMap
# --------------------------------------------------------------------------- #


def test_pmap_set_is_immutable() -> None:
    a = PersistentMap({"x": 1})
    b = a.set("y", 2)
    assert "y" not in a and a["x"] == 1
    assert b["x"] == 1 and b["y"] == 2


def test_pmap_delete_is_immutable_and_idempotent() -> None:
    a = PersistentMap({"x": 1, "y": 2})
    b = a.delete("x").delete("missing")
    assert a["x"] == 1
    assert "x" not in b and b["y"] == 2


def test_pmap_evolver_batches_then_finishes_once() -> None:
    base = PersistentMap({"x": 1})
    ev = base.mutate()
    ev.set("y", 2).set("z", 3).delete("x")
    out = ev.finish()
    assert base["x"] == 1 and len(base) == 1  # base untouched by the evolver
    assert dict(out.items()) == {"y": 2, "z": 3}
    with pytest.raises(RuntimeError):
        ev.set("w", 4)
    with pytest.raises(RuntimeError):
        ev.finish()


# --------------------------------------------------------------------------- #
# NodeRecord shape invariant
# --------------------------------------------------------------------------- #


def test_record_rejects_branch_and_ref_together() -> None:
    with pytest.raises(ValueError):
        NodeRecord(
            type="collection",
            children=(),
            ref=Reference(path=ZarrPath(path="../x.zarr")),
        )


def test_record_shapes() -> None:
    branch = NodeRecord(type="collection", children=())
    leaf = NodeRecord(type="singlescale")
    reference = NodeRecord(
        type="multiscale", ref=Reference(path=ZarrPath(path="../image.zarr"))
    )
    assert branch.is_branch and not branch.is_reference
    assert leaf.is_leaf
    assert reference.is_reference and not reference.is_branch


# --------------------------------------------------------------------------- #
# NodeTree construction, navigation, indices
# --------------------------------------------------------------------------- #


def _sample() -> tuple[NodeTree, dict[str, tuple[str, ...]]]:
    """root → {img → 0, labels → nuclei}; returns the collection and key map."""
    c = NodeTree.of(NodeRecord(type="collection", id="root", children=()))
    c, img = c.add_child(ROOT, NodeRecord(type="multiscale", id="img", children=()))
    c, zero = c.add_child(img, NodeRecord(type="singlescale", id="0"))
    c, labels = c.add_child(
        ROOT, NodeRecord(type="collection", id="labels", children=())
    )
    c, nuclei = c.add_child(labels, NodeRecord(type="multiscale", id="nuclei"))
    keys = {"root": ROOT, "img": img, "0": zero, "labels": labels, "nuclei": nuclei}
    return c, keys


def test_walk_is_depth_first_in_order() -> None:
    c, k = _sample()
    assert list(c.walk()) == [k["root"], k["img"], k["0"], k["labels"], k["nuclei"]]


def test_find_and_parent_and_children() -> None:
    c, k = _sample()
    assert c.find("nuclei") == (k["nuclei"],)
    assert c.parent_id(k["nuclei"]) == k["labels"]
    assert c.children_ids(k["root"]) == (k["img"], k["labels"])
    assert c.find("absent") == ()


def test_keys_encode_path_not_namespaced_id() -> None:
    c, k = _sample()
    # identity is the structural path; the record keeps its pristine local id.
    assert k["nuclei"] == ("labels", "nuclei")
    assert c.record(k["nuclei"]).id == "nuclei"


# --------------------------------------------------------------------------- #
# Immutability + structural sharing
# --------------------------------------------------------------------------- #


def test_edit_returns_new_collection_and_shares_untouched_records() -> None:
    c, k = _sample()
    c2 = c.set_attrs(k["img"], {"role": "raw"})
    # original untouched
    assert "role" not in c.record(k["img"]).attributes
    assert c2.record(k["img"]).attributes["role"] == "raw"
    # ancestors not rebuilt, siblings shared by identity (no deep copy)
    assert c2.record(k["labels"]) is c.record(k["labels"])
    assert c2.record(k["nuclei"]) is c.record(k["nuclei"])


def test_set_attributes_replaces_and_drop_removes() -> None:
    c, k = _sample()
    c = c.set_attributes(k["img"], {"a": 1, "b": 2})
    assert dict(c.record(k["img"]).attributes) == {"a": 1, "b": 2}
    c = c.drop_attrs(k["img"], ("a",))
    assert dict(c.record(k["img"]).attributes) == {"b": 2}


def test_rename() -> None:
    c, k = _sample()
    c = c.rename(k["img"], "Raw image")
    assert c.record(k["img"]).name == "Raw image"


# --------------------------------------------------------------------------- #
# Positional identity: same local id in two places stays distinct & pristine
# --------------------------------------------------------------------------- #


def test_same_local_id_under_two_parents_yields_distinct_keys() -> None:
    c, k = _sample()
    c, a = c.add_child(k["img"], NodeRecord(type="singlescale", id="shared"))
    c, b = c.add_child(k["labels"], NodeRecord(type="singlescale", id="shared"))
    assert a != b
    assert set(c.find("shared")) == {a, b}
    assert c.record(a).id == c.record(b).id == "shared"  # pristine, not rewritten


def test_duplicate_id_among_siblings_falls_back_to_positional_segment() -> None:
    c = NodeTree.of(NodeRecord(type="collection", id="root", children=()))
    c, first = c.add_child(ROOT, NodeRecord(type="singlescale", id="dup"))
    c, second = c.add_child(ROOT, NodeRecord(type="singlescale", id="dup"))
    assert first == ("dup",) and second != first
    assert set(c.find("dup")) == {first, second}


# --------------------------------------------------------------------------- #
# remove keeps the indices in step
# --------------------------------------------------------------------------- #


def test_remove_subtree_updates_nodes_and_indices() -> None:
    c, k = _sample()
    c2 = c.remove(k["labels"])
    assert k["labels"] not in c2 and k["nuclei"] not in c2
    assert c2.find("nuclei") == ()
    assert c2.children_ids(ROOT) == (k["img"],)
    # original is untouched
    assert k["nuclei"] in c


def test_remove_root_raises_and_missing_is_idempotent() -> None:
    c, k = _sample()
    with pytest.raises(ValueError):
        c.remove(ROOT)
    assert c.remove(("does", "not", "exist")) is c


def test_replace_swaps_subtree_keeping_key_and_position() -> None:
    c, k = _sample()
    stub = NodeRecord(
        type="multiscale", id="img", ref=Reference(path=ZarrPath(path="/img.zarr"))
    )
    c2 = c.replace(k["img"], stub)
    # same key, same sibling position, descendants gone
    assert c2.children_ids(ROOT) == (k["img"], k["labels"])
    assert c2.record(k["img"]).is_reference
    assert k["0"] not in c2 and c2.find("0") == ()
    # indices follow the new record
    assert c2.find("img") == (k["img"],)
    assert c2.referrers("img") == ()  # Reference above carries no id
    # original untouched
    assert k["0"] in c and not c.record(k["img"]).is_reference


def test_replace_updates_indices_on_id_change() -> None:
    c, k = _sample()
    c2 = c.replace(k["labels"], NodeRecord(type="collection", id="annotations"))
    assert c2.find("labels") == () and c2.find("nuclei") == ()
    assert c2.find("annotations") == (k["labels"],)  # key is structural, kept


def test_replace_missing_raises() -> None:
    c, _ = _sample()
    with pytest.raises(KeyError):
        c.replace(("absent",), NodeRecord(type="collection", id="x"))


# --------------------------------------------------------------------------- #
# refs index (structural references)
# --------------------------------------------------------------------------- #


def test_tree_builder_matches_incremental_add_child() -> None:
    # Build the same tree two ways: incremental add_child vs the bulk TreeBuilder.
    tb = TreeBuilder(NodeRecord(type="collection", id="root", children=()))
    img = tb.add_child(
        ROOT, NodeRecord(type="multiscale", id="img", attributes={"r": 1}, children=())
    )
    tb.add_child(img, NodeRecord(type="singlescale", id="0"))
    tb.add_child(ROOT, NodeRecord(type="collection", id="dup"))
    tb.add_child(
        ROOT, NodeRecord(type="collection", id="dup")
    )  # duplicate -> positional
    built = tb.finish()

    inc, _ = _sample_like_builder()
    assert [built.record(n).id for n in built.walk()] == [
        inc.record(n).id for n in inc.walk()
    ]
    assert dict(built.record(("img",)).attributes) == {"r": 1}
    assert len(built.find("dup")) == 2  # both kept, distinct keys


def _sample_like_builder() -> tuple[NodeTree, None]:
    c = NodeTree.of(NodeRecord(type="collection", id="root", children=()))
    c, img = c.add_child(
        ROOT, NodeRecord(type="multiscale", id="img", attributes={"r": 1}, children=())
    )
    c, _ = c.add_child(img, NodeRecord(type="singlescale", id="0"))
    c, _ = c.add_child(ROOT, NodeRecord(type="collection", id="dup"))
    c, _ = c.add_child(ROOT, NodeRecord(type="collection", id="dup"))
    return c, None


def test_tree_builder_is_single_use() -> None:
    tb = TreeBuilder(NodeRecord(type="collection", id="root", children=()))
    tb.finish()
    with pytest.raises(RuntimeError):
        tb.add_child(ROOT, NodeRecord(type="multiscale", id="x"))
    with pytest.raises(RuntimeError):
        tb.finish()


def test_refs_index_tracks_reference_targets() -> None:
    c = NodeTree.of(NodeRecord(type="collection", id="root", children=()))
    stub = NodeRecord(
        type="multiscale",
        id="image",
        ref=Reference(path=ZarrPath(path="../image.zarr"), id="image"),
    )
    c, ref_key = c.add_child(ROOT, stub)
    assert c.referrers("image") == (ref_key,)
    c = c.remove(ref_key)
    assert c.referrers("image") == ()
