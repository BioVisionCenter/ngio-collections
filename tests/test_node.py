"""Tests for the public `Node` handle (no IO).

Covers handle-rooted construction with minted UUIDs, typed subclasses,
navigation, trait and field lenses, the embedding guard, validation through the
handle, and the functional edits.
"""

from __future__ import annotations

import pytest

import ngio_collections as ngc
from ngio_collections.models._errors import NodeStateError
from tests._builders import collection, external, multiscale
from tests.conftest import mk, requires_pydantic

RENDER = "https://napari.org/ngff/rendering"


def _tree() -> ngc.Node:
    """root[collection] → {img (external multiscale), labels[collection] → nuclei (external)}."""
    labels = collection(2, external(3, "./nuclei"), name="labels")
    return collection(0, external(1, "./img"), labels, name="root")


def test_construction_mints_uuids_and_types_handles() -> None:
    root = _tree()
    assert isinstance(root, ngc.CollectionNode)
    assert isinstance(root.find(mk(1)), ngc.MultiscaleNode)
    assert [c.id for c in root.children()] == [mk(1), mk(2)]
    fresh = ngc.new_collection(name="auto")
    assert ngc.is_uuid(fresh.id) and fresh.name == "auto"
    with pytest.raises(ValueError):
        ngc.new_node("collection", id="img")  # not a UUID


def test_walk_find_and_find_by_name_are_subtree_scoped() -> None:
    root = _tree()
    assert [n.id for n in root.walk()] == [mk(0), mk(1), mk(2), mk(3)]
    labels = root.find(mk(2))
    assert labels is not None and [n.id for n in labels.walk()] == [mk(2), mk(3)]
    assert labels.find(mk(1)) is None
    assert root.find(mk(3)).parent().id == mk(2)
    assert [n.id for n in root.find_by_name("labels")] == [mk(2)]
    assert root.find_by_name("nobody") == ()


def test_detached_state_and_origin_url() -> None:
    root = _tree()
    assert (
        root.is_detached and root.document_url is None and root.extension_manifest == ()
    )
    node = ngc.new_node(
        "multiscale", id=mk(1), name="img", origin_url="/data/image.zarr"
    )
    assert not node.is_detached and node.document_url == "/data/image.zarr/zarr.json"
    ref = node.ref()
    assert ref.type == "multiscale" and ref.ref == mk(1)
    assert ref.path is not None and (ref.path.format, ref.path.href) == (
        "absolute",
        "/data/image.zarr",
    )
    assert node.ref_local().to_dict() == {
        "type": "multiscale",
        "ref": mk(1),
    }
    stub = node.stub()
    assert stub.is_external and stub.is_detached and stub.id == mk(1)
    assert stub.ref_path == "/data/image.zarr" and stub.name == "img"
    with pytest.raises(NodeStateError):
        root.require_document_url()
    with pytest.raises(NodeStateError):
        root.stub()


@requires_pydantic
def test_multiscale_handle_exposes_fields() -> None:
    ms = multiscale(4, axis_names=("z", "y", "x"), levels=3)
    assert isinstance(ms, ngc.MultiscaleNode)
    assert [a.name for a in ms.coordinate_systems[0].axes] == ["z", "y", "x"]
    assert [s.path.href for s in ms.scales] == ["./s0", "./s1", "./s2"]
    s1 = ms.scale(ms.scales[1].id)
    assert s1 is not None and s1.coordinate_transformations[0].scale == [2.0, 2.0, 2.0]
    assert ms.coordinate_system(mk(99)) is None
    edited = ms.set_scales(ms.scales[:1])
    assert len(edited.scales) == 1 and len(ms.scales) == 3
    assert set(ms.fields) == {"coordinate_systems", "scales"}
    assert ms.get_field("scales") == ms.fields["scales"]


def test_add_rejects_an_embedded_multiscale() -> None:
    root = ngc.new_collection(id=mk(0))
    with pytest.raises(NodeStateError):
        root.add(multiscale(4))
    with pytest.raises(NodeStateError):
        ngc.new_collection(children=[multiscale(4)])
    linked = root.add(multiscale(4, path=ngc.ZarrPath(href="./ms4")))
    assert linked.find(mk(4)).is_external
    with pytest.raises(ValueError):
        root.add_external(ngc.new_collection(id=mk(5)))  # not external


def test_set_path_makes_a_leaf_external_and_back() -> None:
    root = ngc.new_collection(id=mk(0), children=[ngc.new_collection(id=mk(5))])
    out = root.find(mk(5)).set_path(ngc.JsonPath(href="./child.json"))
    assert out.find(mk(5)).is_external and out.find(mk(5)).ref_path == "./child.json"
    back = out.find(mk(5)).set_path(None)
    assert not back.find(mk(5)).is_external
    with pytest.raises(NodeStateError):
        _tree().find(mk(2)).set_path(ngc.JsonPath(href="./x.json"))  # has children


def test_new_node_rejects_children_on_an_external_node() -> None:
    with pytest.raises(ValueError):
        ngc.new_node(
            "collection",
            path=ngc.ZarrPath(href="/img.zarr"),
            children=[ngc.new_collection(id=mk(1))],
        )


def test_add_variadic_matches_chained_adds() -> None:
    a, b, c = (ngc.new_collection(id=mk(i)) for i in (1, 2, 3))
    fanned = ngc.new_collection(id=mk(0)).add(a, b, c)
    chained = ngc.new_collection(id=mk(0)).add(a).add(b).add(c)
    assert [n.id for n in fanned.walk()] == [n.id for n in chained.walk()]


def test_subtree_extracts_independent_detached_tree() -> None:
    root = _tree()
    labels = root.find(mk(2)).subtree()
    assert labels.id == mk(2) and labels.is_detached and labels.parent() is None
    assert [n.id for n in labels.walk()] == [mk(2), mk(3)]
    assert labels.find(mk(1)) is None
    edited = labels.find(mk(3)).set_trait({"type": "labels", "source": []})
    assert edited.id == mk(2) and "labels" in edited.find(mk(3)).traits
    assert "labels" not in root.find(mk(3)).traits


# --------------------------------------------------------------------------- #
# Traits: lenses and edits
# --------------------------------------------------------------------------- #


@requires_pydantic
def test_trait_lenses_and_typed_edits() -> None:
    root = _tree()
    well = ngc.WellTrait(row_index=0, column_index=1)
    edited = root.find(mk(2)).set_trait(well)  # tree-out: edited is the new root
    node = edited.find(mk(2))
    assert node[ngc.WellTrait].column_index == 1
    assert node.get_trait(ngc.PlateTrait) is None
    assert node.has_trait(ngc.WellTrait) and node.has_trait("well")
    assert ngc.WellTrait in node and "well" in node and "plate" not in node
    assert node.traits["well"] == {"type": "well", "row_index": 0, "column_index": 1}
    assert root.find(mk(2)).get_trait(ngc.WellTrait) is None  # original untouched
    with pytest.raises(KeyError):
        node[ngc.PlateTrait]


@requires_pydantic
def test_set_trait_drops_none_fields_and_writes_snake_case() -> None:
    root = _tree()
    scene = ngc.SceneTrait(
        coordinate_systems=[ngc.CoordinateSystem(id=mk(5), axes=[ngc.Axis(name="x")])]
    )
    edited = root.set_trait(scene)
    assert edited.traits["scene"] == {
        "type": "scene",
        "coordinate_systems": [
            {"type": "coordinate_system", "id": mk(5), "axes": [{"name": "x"}]}
        ],
        "coordinate_transformations": [],
    }


@requires_pydantic
def test_set_traits_upserts_by_type_and_drop_traits() -> None:
    root = _tree()
    root = root.set_traits(
        {"type": RENDER, "contrast_limits": [0, 1]},
        ngc.WellTrait(row_index=0, column_index=0),
    )
    assert list(root.traits) == [RENDER, "well"]
    root = root.set_trait({"type": RENDER, "contrast_limits": [2, 3]})
    assert list(root.traits) == [RENDER, "well"]  # replaced in place
    assert root.traits[RENDER]["contrast_limits"] == [2, 3]
    root = root.drop_traits(ngc.WellTrait, "missing")
    assert list(root.traits) == [RENDER]
    with pytest.raises(ValueError):
        root.set_trait({"contrast_limits": [1]})  # no type


def test_rename_remove_and_fields() -> None:
    root = _tree()
    root = root.find(mk(1)).rename("Raw")
    assert root.find(mk(1)).name == "Raw"
    pruned = root.find(mk(2)).remove()
    assert pruned.find(mk(3)) is None and pruned.id == mk(0)
    with pytest.raises(ValueError):
        root.remove()
    ext = ngc.new_node("https://ngio.example/bench/table", id=mk(7), fields={"rows": 3})
    assert ext.set_field("rows", 4).fields == {"rows": 4}
    assert ext.set_fields({}).fields == {}


# --------------------------------------------------------------------------- #
# Registry and validation through the handle
# --------------------------------------------------------------------------- #


def test_register_node_type_requires_a_uri() -> None:
    class TableNode(ngc.Node):
        pass

    with pytest.raises(ValueError):
        ngc.register_node_type("fractal:table", TableNode)
    ngc.register_node_type("https://fractal.example/ngff/table", TableNode)
    table = ngc.new_node("https://fractal.example/ngff/table", id=mk(8))
    assert isinstance(table, TableNode)
    assert type(ngc.new_node("https://mobie.example/view", id=mk(9))) is ngc.Node


@requires_pydantic
def test_validate_through_handle() -> None:
    plate = ngc.new_collection(
        id=mk(0),
        traits=[
            ngc.PlateTrait(
                rows=[ngc.RowObj(name="A")], columns=[ngc.ColumnObj(name="1")]
            )
        ],
        children=[
            ngc.new_collection(
                id=mk(1), traits=[ngc.WellTrait(row_index=0, column_index=0)]
            )
        ],
    )
    assert plate.find(mk(1)).validate(ngc.RECOMMENDED_VALIDATORS) == []
    orphan = ngc.new_collection(
        id=mk(0),
        children=[
            ngc.new_collection(
                id=mk(1), traits=[ngc.WellTrait(row_index=0, column_index=0)]
            )
        ],
    )
    errors = orphan.find(mk(1)).validate(ngc.RECOMMENDED_VALIDATORS)
    assert [e.validator for e in errors] == ["well_under_plate"]
    assert errors[0].node_uuid == mk(1)
