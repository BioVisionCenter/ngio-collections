"""Tests for the public `Node` handle (no IO).

Covers handle-rooted construction with minted ids, typed subclasses,
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


def test_construction_mints_ids_and_types_handles() -> None:
    root = _tree()
    assert isinstance(root, ngc.CollectionNode)
    assert isinstance(root.find(mk(1)), ngc.MultiscaleNode)
    assert [c.id for c in root.children()] == [mk(1), mk(2)]
    fresh = ngc.new_collection(name="auto")
    assert ngc.is_id(fresh.id) and fresh.name == "auto"
    assert ngc.new_node("collection", id="img").id == "img"  # any id string
    with pytest.raises(ValueError):
        ngc.new_node("collection", id="img/0")  # not a valid id


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
    assert [a.scale for a in ms.arrays] == [None, [2.0] * 3, [4.0] * 3]
    assert [a.path.href for a in ms.arrays] == ["./s0", "./s1", "./s2"]
    s1 = ms.arrays[1]
    assert s1.type == "array" and s1.translation is None
    assert "id" not in ms.fields["data"][0]  # arrays are not declarations
    assert ms.coordinate_system(mk(99)) is None
    (to_physical,) = ms.coordinate_transformations
    assert to_physical.input == ngc.ReferenceObj(type="multiscale", ref=ms.id)
    edited = ms.set_arrays(ms.arrays[:1])
    assert len(edited.arrays) == 1 and len(ms.arrays) == 3
    assert set(ms.fields) == {"coordinateSystems", "coordinateTransformations", "data"}
    assert ms.get_field("data") == ms.fields["data"]
    mapped = ms.set_coordinate_transformations(
        [
            ngc.ScaleTransformation(
                scale=[1.0, 0.1, 0.1],
                input=ngc.ReferenceObj(type="multiscale", ref=ms.id),
                output=ngc.ReferenceObj(type="coordinate_system", ref=mk(0x1004)),
            )
        ]
    )
    (tf,) = mapped.coordinate_transformations
    assert isinstance(tf, ngc.ScaleTransformation) and tf.scale == [1.0, 0.1, 0.1]
    # a multiscale is a leaf: no `nodes` key on the wire
    assert ms.record.children is None


def test_add_embeds_or_links_a_multiscale() -> None:
    root = ngc.new_collection(id=mk(0))
    embedded = root.add(multiscale(4)).find(mk(4))
    assert not embedded.is_external and embedded.record.children is None
    assert ngc.new_collection(children=[multiscale(4)]).find(mk(4)) is not None
    linked = root.add(multiscale(4, path=ngc.ZarrPath(href="./ms4")))
    assert linked.find(mk(4)).is_external
    # made embedded again, a multiscale stays a leaf
    again = linked.find(mk(4)).set_path(None).find(mk(4))
    assert not again.is_external and again.record.children is None
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
def test_set_trait_drops_none_fields_and_writes_wire_keys() -> None:
    root = _tree()
    scene = ngc.SceneTrait(
        coordinate_systems=[ngc.CoordinateSystem(id=mk(5), axes=[ngc.Axis(name="x")])],
        coordinate_transformations=[],
    )
    edited = root.set_trait(scene)
    assert edited.traits["scene"] == {
        "type": "scene",
        "coordinateSystems": [
            {"type": "coordinate_system", "id": mk(5), "axes": [{"name": "x"}]}
        ],
        "coordinateTransformations": [],
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
    assert errors[0].declared_id == mk(1)
