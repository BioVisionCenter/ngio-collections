"""Tests for the public `Node` handle (no IO).

Covers handle-rooted/fluent construction, typed subclasses, navigation, capability
lenses, validation through the handle, and the functional edits.
"""

from __future__ import annotations

import ngio_collections.api as ngc
from ngio_collections.api import CollectionNode, MultiscaleNode, Node, new_node
from ngio_collections.models.attributes import PlateAttribute, WellAttribute


def _build_tree() -> Node:
    """root[collection] → {img[multiscale], labels[collection] → nuclei}."""
    root = new_node("collection", id="root")
    root = root.add(new_node("multiscale", id="img", attributes={"role": "raw"}))
    labels = new_node("collection", id="labels")
    labels = labels.add(new_node("multiscale", id="nuclei"))
    return root.add(labels)


def test_construction_and_typed_subclasses() -> None:
    root = _build_tree()
    assert isinstance(root, CollectionNode)
    assert isinstance(root.find("img"), MultiscaleNode)
    assert [c.id for c in root.children()] == ["img", "labels"]


def test_walk_and_find_are_subtree_scoped() -> None:
    root = _build_tree()
    assert [n.id for n in root.walk()] == ["root", "img", "labels", "nuclei"]
    labels = root.find("labels")
    assert labels is not None
    assert [n.id for n in labels.walk()] == ["labels", "nuclei"]
    assert labels.find("img") is None  # img is outside the labels subtree
    assert root.find("nuclei").parent().id == "labels"


def test_detached_state() -> None:
    root = _build_tree()
    assert root.is_detached and root.document_url is None


def test_subtree_extracts_independent_detached_tree() -> None:
    root = _build_tree()  # root -> {img, labels -> nuclei}
    labels = root.find("labels").subtree()
    assert labels.id == "labels" and labels.is_detached
    assert [n.id for n in labels.walk()] == ["labels", "nuclei"]
    assert labels.parent() is None  # it is its own root now
    assert labels.find("img") is None  # img was outside the subtree
    # editing the subtree returns the subtree root, not the original whole tree
    edited = labels.find("nuclei").set_attrs({"x": 1})
    assert edited.id == "labels" and edited.find("nuclei").attributes["x"] == 1
    # the source tree is untouched
    assert "x" not in root.find("nuclei").attributes


# --------------------------------------------------------------------------- #
# Functional edits return new handles; the source is untouched
# --------------------------------------------------------------------------- #


def test_set_attr_is_immutable_and_typed() -> None:
    root = _build_tree()
    well = WellAttribute(column={"id": "c1"}, row={"id": "r1"})
    edited = root.find("img").set_attr(well)  # tree-out: edited is the new root
    assert edited.find("img")[WellAttribute].column.id == "c1"
    # original collection untouched
    assert root.find("img").get_attr(WellAttribute) is None


def test_set_attrs_merge_and_rename_and_remove() -> None:
    root = _build_tree()
    root = root.find("img").set_attrs({"x": 1})  # each edit returns the tree root
    root = root.find("img").rename("Raw")
    img = root.find("img")
    assert img.attributes["x"] == 1 and img.name == "Raw" and img.attributes["role"] == "raw"
    pruned = root.find("labels").remove()
    assert pruned.find("nuclei") is None and pruned.id == "root"


# --------------------------------------------------------------------------- #
# Validation through the handle (composition)
# --------------------------------------------------------------------------- #


def test_validate_through_handle() -> None:
    plate = new_node("collection", id="plate", attributes={
        "plate": {"columns": [{"id": "c1"}], "rows": [{"id": "r1"}]}
    })
    plate = plate.add(new_node("collection", id="A1", attributes={
        "well": {"column": {"id": "c1"}, "row": {"id": "r1"}}
    }))
    assert plate.find("A1").validate() == []  # well under plate -> ok

    orphan = new_node("collection", id="root")
    orphan = orphan.add(new_node("collection", id="A1", attributes={
        "well": {"column": {"id": "c1"}, "row": {"id": "r1"}}
    }))
    issues = orphan.find("A1").validate()
    assert [i.validator for i in issues] == ["well-under-plate"]
    assert plate.find("A1").has(PlateAttribute) is False  # the plate is the parent
