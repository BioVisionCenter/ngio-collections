"""Tests for the public `Node` handle (no IO).

Covers handle-rooted/fluent construction, typed subclasses, navigation, capability
lenses, validation through the handle, and the functional edits.
"""

from __future__ import annotations

import pytest

import ngio_collections.api as ngc
from ngio_collections.api import (
    CollectionNode,
    MultiscaleNode,
    Node,
    Reference,
    new_node,
)
from ngio_collections.models._config import NodeStateError
from ngio_collections.models._paths import ZarrPath
from ngio_collections.models.attributes import (
    Axis,
    CoordinateSystem,
    CoordinateSystemsAttribute,
    PlateAttribute,
    WellAttribute,
)


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


def test_new_node_with_origin_url_is_document_backed() -> None:
    node = new_node("multiscale", id="img", origin_url="/data/image.zarr")
    assert not node.is_detached
    assert node.document_url == "/data/image.zarr/zarr.json"  # normalized

    # provenance-dependent helpers work without any IO
    locator = node.ref()
    assert locator.id == "img" and locator.path.path == "/data/image.zarr"
    stub = node.ref_stub()
    assert stub.is_reference and stub.id == "img"
    assert stub.ref_path == "/data/image.zarr"


def test_grafting_preserves_origin_url() -> None:
    backed = new_node("multiscale", id="img", origin_url="/data/image.zarr")
    root = new_node("collection", id="root").add(backed)
    grafted = root.find("img")
    assert grafted.document_url == "/data/image.zarr/zarr.json"
    assert root.is_detached  # the root itself carries no origin


def test_new_node_with_children() -> None:
    root = new_node(
        "collection",
        id="root",
        children=[
            new_node("multiscale", id="a"),
            new_node("collection", id="b", children=[new_node("multiscale", id="c")]),
        ],
    )
    assert [n.id for n in root.walk()] == ["root", "a", "b", "c"]


def test_new_node_rejects_children_on_a_reference_stub() -> None:
    with pytest.raises(ValueError):
        new_node(
            "multiscale",
            ref=Reference(path=ZarrPath(path="/img.zarr")),
            children=[new_node("multiscale", id="a")],
        )


def test_add_variadic_matches_chained_adds() -> None:
    a, b, c = (new_node("multiscale", id=i) for i in "abc")
    fanned = new_node("collection", id="root").add(a, b, c)
    chained = new_node("collection", id="root").add(a).add(b).add(c)
    assert [n.id for n in fanned.walk()] == [n.id for n in chained.walk()]
    assert [n.id for n in fanned.add().walk()] == [n.id for n in fanned.walk()]


def test_add_ref_variadic_and_validates_all_stubs() -> None:
    s1 = new_node("multiscale", id="a", ref=Reference(path=ZarrPath(path="/a.zarr")))
    s2 = new_node("multiscale", id="b", ref=Reference(path=ZarrPath(path="/b.zarr")))
    root = new_node("collection", id="root").add_ref(s1, s2)
    assert [c.id for c in root.children()] == ["a", "b"]
    assert all(c.is_reference for c in root.children())
    with pytest.raises(ValueError):
        root.add_ref(s1, new_node("multiscale", id="plain"))


def test_ref_path_shortcut() -> None:
    stub = new_node("multiscale", ref=Reference(path=ZarrPath(path="/data/img.zarr")))
    assert stub.ref_path == "/data/img.zarr"
    assert new_node("collection", id="root").ref_path is None


def test_require_id_and_document_url_narrow_or_raise() -> None:
    root = _build_tree()
    assert root.find("img").require_id() == "img"
    with pytest.raises(NodeStateError):
        new_node("multiscale").require_id()
    with pytest.raises(NodeStateError):
        root.require_document_url()  # detached
    with pytest.raises(NodeStateError):
        root.ref_stub()  # needs a backing document


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


def test_set_attr_drops_none_fields() -> None:
    root = _build_tree()
    well = WellAttribute(column={"id": "c1"}, row={"id": "r1"})
    edited = root.find("img").set_attr(well)
    # no `path: null` on the references, recursively
    assert edited.find("img").attributes["well"] == {
        "column": {"id": "c1"},
        "row": {"id": "r1"},
    }
    systems = CoordinateSystemsAttribute(
        [CoordinateSystem(id="s", axes=[Axis(name="x")])]
    )
    edited = edited.find("img").set_attr(systems)
    # no `type/unit/discrete/longName: null` on the axis
    assert edited.find("img").attributes["coordinateSystems"] == [
        {"id": "s", "axes": [{"name": "x"}]}
    ]


def test_set_attrs_merge_and_rename_and_remove() -> None:
    root = _build_tree()
    root = root.find("img").set_attrs({"x": 1})  # each edit returns the tree root
    root = root.find("img").rename("Raw")
    img = root.find("img")
    assert (
        img.attributes["x"] == 1
        and img.name == "Raw"
        and img.attributes["role"] == "raw"
    )
    pruned = root.find("labels").remove()
    assert pruned.find("nuclei") is None and pruned.id == "root"


def test_set_attrs_with_drop_is_one_edit() -> None:
    root = _build_tree()
    root = root.find("img").set_attrs({"x": 1}, drop=["role"])
    img = root.find("img")
    assert img.attributes == {"x": 1}  # merged and dropped in one new tree


def test_set_attrs_drop_wins_on_overlapping_key() -> None:
    root = _build_tree()
    root = root.find("img").set_attrs({"role": "new", "x": 1}, drop=["role"])
    assert root.find("img").attributes == {"x": 1}


def test_set_attrs_drop_accepts_attribute_classes() -> None:
    well = WellAttribute(column={"id": "c1"}, row={"id": "r1"})
    root = _build_tree().find("img").set_attr(well)
    assert WellAttribute in root.find("img")
    root = root.find("img").set_attrs({"x": 1}, drop=[WellAttribute])
    img = root.find("img")
    assert WellAttribute not in img and img.attributes["x"] == 1


# --------------------------------------------------------------------------- #
# Validation through the handle (composition)
# --------------------------------------------------------------------------- #


def test_validate_through_handle() -> None:
    plate = new_node(
        "collection",
        id="plate",
        attributes={"plate": {"columns": [{"id": "c1"}], "rows": [{"id": "r1"}]}},
    )
    plate = plate.add(
        new_node(
            "collection",
            id="A1",
            attributes={"well": {"column": {"id": "c1"}, "row": {"id": "r1"}}},
        )
    )
    validators = (ngc.well_under_plate, ngc.scale_matches_axes)
    assert plate.find("A1").validate(validators) == []  # well under plate -> ok

    orphan = new_node("collection", id="root")
    orphan = orphan.add(
        new_node(
            "collection",
            id="A1",
            attributes={"well": {"column": {"id": "c1"}, "row": {"id": "r1"}}},
        )
    )
    errors = orphan.find("A1").validate(validators)
    assert [e.validator for e in errors] == ["well_under_plate"]
    assert plate.find("A1").has(PlateAttribute) is False  # the plate is the parent
