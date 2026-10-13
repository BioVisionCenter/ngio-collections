"""Tests for the public `Node` handle (no IO).

Covers handle-rooted/fluent construction, typed subclasses, navigation, capability
lenses, validation through the handle, and the functional edits.
"""

from __future__ import annotations

import re

import pytest
from conftest import uid

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
from ngio_collections.models._references import UUID_PATTERN
from ngio_collections.models.attributes import (
    Axis,
    CoordinateSystem,
    CoordinateSystemsAttribute,
    PlateAttribute,
    WellAttribute,
)

WELL = WellAttribute(
    column={"type": "column", "ref": uid("c1")}, row={"type": "row", "ref": uid("r1")}
)


def _build_tree() -> Node:
    """root[collection] → {img[multiscale], labels[collection] → nuclei}."""
    root = new_node("collection", id=uid("root"), name="test")
    root = root.add(
        new_node("multiscale", id=uid("img"), name="test", attributes={"role": "raw"})
    )
    labels = new_node("collection", id=uid("labels"), name="test")
    labels = labels.add(new_node("multiscale", id=uid("nuclei"), name="test"))
    return root.add(labels)


def test_construction_and_typed_subclasses() -> None:
    root = _build_tree()
    assert isinstance(root, CollectionNode)
    assert isinstance(root.find(uid("img")), MultiscaleNode)
    assert [c.id for c in root.children()] == [uid("img"), uid("labels")]


def test_new_node_mints_a_uuid_when_no_id_is_given() -> None:
    node = new_node("collection", name="anonymous")
    assert node.id is not None and re.fullmatch(UUID_PATTERN, node.id)
    assert new_node("collection").id != node.id


def test_walk_and_find_are_subtree_scoped() -> None:
    root = _build_tree()
    assert [n.id for n in root.walk()] == [
        uid("root"),
        uid("img"),
        uid("labels"),
        uid("nuclei"),
    ]
    labels = root.find(uid("labels"))
    assert labels is not None
    assert [n.id for n in labels.walk()] == [uid("labels"), uid("nuclei")]
    assert labels.find(uid("img")) is None  # img is outside the labels subtree
    assert root.find(uid("nuclei")).parent().id == uid("labels")


def test_detached_state() -> None:
    root = _build_tree()
    assert root.is_detached and root.document_url is None


def test_new_node_with_origin_url_is_document_backed() -> None:
    node = new_node("multiscale", id=uid("img"), origin_url="/data/image.zarr")
    assert not node.is_detached
    assert node.document_url == "/data/image.zarr/zarr.json"  # normalized

    # provenance-dependent helpers work without any IO
    locator = node.ref()
    assert (locator.type, locator.ref) == ("multiscale", uid("img"))
    assert locator.path.href == "/data/image.zarr" and locator.path.format == "absolute"
    stub = node.ref_stub()
    assert stub.is_reference and stub.id is None
    assert stub.record.ref.ref == uid("img") and stub.ref_path == "/data/image.zarr"


def test_grafting_preserves_origin_url() -> None:
    backed = new_node("multiscale", id=uid("img"), origin_url="/data/image.zarr")
    root = new_node("collection", id=uid("root"), name="root").add(backed)
    grafted = root.find(uid("img"))
    assert grafted.document_url == "/data/image.zarr/zarr.json"
    assert root.is_detached  # the root itself carries no origin


def test_new_node_with_children() -> None:
    root = new_node(
        "collection",
        id=uid("root"),
        children=[
            new_node("multiscale", id=uid("a")),
            new_node(
                "collection", id=uid("b"), children=[new_node("multiscale", id=uid("c"))]
            ),
        ],
    )
    assert [n.id for n in root.walk()] == [uid("root"), uid("a"), uid("b"), uid("c")]


def test_new_node_rejects_children_on_a_reference_stub() -> None:
    with pytest.raises(ValueError):
        new_node(
            "multiscale",
            ref=Reference(ref=uid("x"), path=ZarrPath(href="/img.zarr")),
            children=[new_node("multiscale", id=uid("a"))],
        )


def test_new_node_rejects_id_or_name_on_a_reference_stub() -> None:
    ref = Reference(ref=uid("x"), path=ZarrPath(href="/img.zarr"))
    with pytest.raises(ValueError):
        new_node("multiscale", id=uid("x"), ref=ref)
    with pytest.raises(ValueError):
        new_node("multiscale", name="x", ref=ref)
    with pytest.raises(ValueError):
        new_node("multiscale", attributes={"overlay": 1}, ref=ref)


def test_add_variadic_matches_chained_adds() -> None:
    a, b, c = (new_node("multiscale", id=uid(i)) for i in "abc")
    fanned = new_node("collection", id=uid("root")).add(a, b, c)
    chained = new_node("collection", id=uid("root")).add(a).add(b).add(c)
    assert [n.id for n in fanned.walk()] == [n.id for n in chained.walk()]
    assert [n.id for n in fanned.add().walk()] == [n.id for n in fanned.walk()]


def test_add_ref_variadic_and_validates_all_stubs() -> None:
    s1 = new_node("multiscale", ref=Reference(ref=uid("a"), path=ZarrPath(href="/a")))
    s2 = new_node("multiscale", ref=Reference(ref=uid("b"), path=ZarrPath(href="/b")))
    root = new_node("collection", id=uid("root")).add_ref(s1, s2)
    assert [c.record.ref.ref for c in root.children()] == [uid("a"), uid("b")]
    assert all(c.is_reference for c in root.children())
    assert root.tree.referrers(uid("a")) == (root.children()[0].node_id,)
    with pytest.raises(ValueError):
        root.add_ref(s1, new_node("multiscale", id=uid("plain")))


def test_ref_path_shortcut() -> None:
    stub = new_node(
        "multiscale", ref=Reference(ref=uid("x"), path=ZarrPath(href="/data/img.zarr"))
    )
    assert stub.ref_path == "/data/img.zarr"
    bare = new_node("multiscale", ref=Reference(ref=uid("x")))
    assert bare.ref_path is None and bare.ref().path is None
    assert new_node("collection", id=uid("root")).ref_path is None


def test_require_id_and_document_url_narrow_or_raise() -> None:
    root = _build_tree()
    assert root.find(uid("img")).require_id() == uid("img")
    with pytest.raises(NodeStateError):
        new_node("multiscale", ref=Reference(ref=uid("x"))).require_id()
    with pytest.raises(NodeStateError):
        root.require_document_url()  # detached
    with pytest.raises(NodeStateError):
        root.ref_stub()  # needs a backing document


def test_subtree_extracts_independent_detached_tree() -> None:
    root = _build_tree()  # root -> {img, labels -> nuclei}
    labels = root.find(uid("labels")).subtree()
    assert labels.id == uid("labels") and labels.is_detached
    assert [n.id for n in labels.walk()] == [uid("labels"), uid("nuclei")]
    assert labels.parent() is None  # it is its own root now
    assert labels.find(uid("img")) is None  # img was outside the subtree
    # editing the subtree returns the subtree root, not the original whole tree
    edited = labels.find(uid("nuclei")).set_attrs({"x": 1})
    assert edited.id == uid("labels")
    assert edited.find(uid("nuclei")).attributes["x"] == 1
    # the source tree is untouched
    assert "x" not in root.find(uid("nuclei")).attributes


# --------------------------------------------------------------------------- #
# Functional edits return new handles; the source is untouched
# --------------------------------------------------------------------------- #


def test_set_attr_is_immutable_and_typed() -> None:
    root = _build_tree()
    edited = root.find(uid("img")).set_attr(WELL)  # tree-out: edited is the new root
    assert edited.find(uid("img"))[WellAttribute].column.ref == uid("c1")
    # original collection untouched
    assert root.find(uid("img")).get_attr(WellAttribute) is None


def test_set_attr_drops_none_fields() -> None:
    root = _build_tree()
    edited = root.find(uid("img")).set_attr(WELL)
    # no `path: null` on the references, recursively
    assert edited.find(uid("img")).attributes["well"] == {
        "column": {"type": "column", "ref": uid("c1")},
        "row": {"type": "row", "ref": uid("r1")},
    }
    systems = CoordinateSystemsAttribute(
        [CoordinateSystem(id="s", axes=[Axis(name="x")])]
    )
    edited = edited.find(uid("img")).set_attr(systems)
    # no `type/unit/discrete/longName: null` on the axis
    assert edited.find(uid("img")).attributes["coordinateSystems"] == [
        {"id": "s", "axes": [{"name": "x"}]}
    ]


def test_set_attrs_merge_and_rename_and_remove() -> None:
    root = _build_tree()
    root = root.find(uid("img")).set_attrs({"x": 1})  # each edit returns the root
    root = root.find(uid("img")).rename("Raw")
    img = root.find(uid("img"))
    assert (
        img.attributes["x"] == 1
        and img.name == "Raw"
        and img.attributes["role"] == "raw"
    )
    pruned = root.find(uid("labels")).remove()
    assert pruned.find(uid("nuclei")) is None and pruned.id == uid("root")


def test_set_attrs_with_drop_is_one_edit() -> None:
    root = _build_tree()
    root = root.find(uid("img")).set_attrs({"x": 1}, drop=["role"])
    assert root.find(uid("img")).attributes == {"x": 1}  # merged and dropped at once


def test_set_attrs_drop_wins_on_overlapping_key() -> None:
    root = _build_tree()
    root = root.find(uid("img")).set_attrs({"role": "new", "x": 1}, drop=["role"])
    assert root.find(uid("img")).attributes == {"x": 1}


def test_set_attrs_drop_accepts_attribute_classes() -> None:
    root = _build_tree().find(uid("img")).set_attr(WELL)
    assert WellAttribute in root.find(uid("img"))
    root = root.find(uid("img")).set_attrs({"x": 1}, drop=[WellAttribute])
    img = root.find(uid("img"))
    assert WellAttribute not in img and img.attributes["x"] == 1


# --------------------------------------------------------------------------- #
# Validation through the handle (composition)
# --------------------------------------------------------------------------- #


def _well() -> dict:
    return {
        "well": {
            "column": {"type": "column", "ref": uid("c1")},
            "row": {"type": "row", "ref": uid("r1")},
        }
    }


def test_validate_through_handle() -> None:
    plate = new_node(
        "collection",
        id=uid("plate"),
        attributes={"plate": {"columns": [{"id": "c1"}], "rows": [{"id": "r1"}]}},
    )
    plate = plate.add(new_node("collection", id=uid("A1"), attributes=_well()))
    validators = (ngc.well_under_plate, ngc.scale_matches_axes)
    assert plate.find(uid("A1")).validate(validators) == []  # well under plate

    orphan = new_node("collection", id=uid("root"))
    orphan = orphan.add(new_node("collection", id=uid("A1"), attributes=_well()))
    errors = orphan.find(uid("A1")).validate(validators)
    assert [e.validator for e in errors] == ["well_under_plate"]
    assert plate.find(uid("A1")).has(PlateAttribute) is False  # plate is the parent
