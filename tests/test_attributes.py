"""Typed attribute access on nodes: subscript reads, membership, and the
functional `set_attr` / `drop_attr` writes that return a new tree.

The raw `attributes` dict stays the source of truth; typed models are a
validating view layered on top, and every write is immutable (returns a new
root, leaves the original untouched)."""

import pytest

import ngio_collections as ngc


def _tree() -> ngc.CollectionNode:
    return ngc.CollectionNode(
        id="root",
        nodes=(ngc.MultiscaleNode(id="img"),),
    )


def _plate() -> ngc.PlateAttribute:
    return ngc.PlateAttribute(
        columns=[ngc.ColumnObj(id="1"), ngc.ColumnObj(id="2")],
        rows=[ngc.RowObj(id="A")],
    )


def test_set_attr_instance_then_subscript_read():
    plate = _plate()
    root = _tree().set_attr(id="img", value=plate)

    img = root.find(id="img")
    assert ngc.PlateAttribute in img
    assert img[ngc.PlateAttribute].rows == plate.rows
    assert [c.id for c in img[ngc.PlateAttribute].columns] == ["1", "2"]


def test_set_attr_accepts_raw_dict_with_explicit_type():
    raw = {"columns": [{"id": "1"}], "rows": [{"id": "A"}]}
    root = _tree().set_attr(id="img", attr=ngc.PlateAttribute, value=raw)

    plate = root.find(id="img")[ngc.PlateAttribute]
    assert [r.id for r in plate.rows] == ["A"]


def test_set_attr_is_immutable():
    original = _tree()
    root = original.set_attr(id="img", value=_plate())

    assert ngc.PlateAttribute in root.find(id="img")
    assert ngc.PlateAttribute not in original.find(id="img")


def test_set_attr_raw_dict_without_type_raises():
    with pytest.raises(TypeError):
        _tree().set_attr(id="img", value={"columns": [], "rows": []})


def test_membership_and_getitem_missing():
    img = _tree().find(id="img")
    assert ngc.PlateAttribute not in img
    assert img.get_attr(ngc.PlateAttribute) is None
    with pytest.raises(KeyError):
        _ = img[ngc.PlateAttribute]


def test_drop_attr_removes_key():
    root = _tree().set_attr(id="img", value=_plate())
    dropped = root.drop_attr(id="img", attr=ngc.PlateAttribute)

    assert ngc.PlateAttribute in root.find(id="img")  # original kept
    assert ngc.PlateAttribute not in dropped.find(id="img")


def test_set_attr_stores_spec_shaped_raw_dict():
    root = _tree().set_attr(id="img", value=_plate())
    raw = root.find(id="img").attributes["plate"]
    # exclude_none keeps the dump spec-shaped: optional unset names are dropped.
    assert raw["columns"] == [{"id": "1"}, {"id": "2"}]
    assert "acquisitions" in raw


def test_list_attribute_roundtrip():
    systems = ngc.CoordinateSystemsAttribute(
        [ngc.CoordinateSystem(id="cs0", axes=[{"name": "x"}])]
    )
    root = _tree().set_attr(id="img", value=systems)

    img = root.find(id="img")
    assert ngc.CoordinateSystemsAttribute in img
    assert img[ngc.CoordinateSystemsAttribute].root[0].id == "cs0"


def test_typed_axis_roundtrip():
    systems = ngc.CoordinateSystemsAttribute(
        [
            ngc.CoordinateSystem(
                id="cs0",
                axes=[
                    ngc.Axis(name="x", type="space", unit="micrometer"),
                    ngc.Axis(name="c", type="channel", discrete=True),
                ],
            )
        ]
    )
    root = _tree().set_attr(id="img", value=systems)

    axes = root.find(id="img")[ngc.CoordinateSystemsAttribute].root[0].axes
    assert [a.name for a in axes] == ["x", "c"]
    assert axes[0].unit == "micrometer"
    assert axes[1].discrete is True


def test_scene_with_typed_transformations_roundtrip():
    scene = ngc.SceneAttribute(
        coordinate_systems=[
            ngc.CoordinateSystem(id="cs0", axes=[ngc.Axis(name="x")])
        ],
        coordinate_transformations=[
            ngc.SequenceTransformation(
                input=ngc.ReferenceObj(id="cs0"),
                output=ngc.ReferenceObj(id="cs1"),
                transformations=[
                    ngc.ScaleTransformation(scale=[1.0, 1.0]),
                    ngc.TranslationTransformation(translation=[0.0, 5.0]),
                ],
            )
        ],
    )
    root = _tree().set_attr(id="img", value=scene)

    out = root.find(id="img")[ngc.SceneAttribute]
    seq = out.coordinate_transformations[0]
    assert isinstance(seq, ngc.SequenceTransformation)
    assert isinstance(seq.transformations[0], ngc.ScaleTransformation)
    assert seq.transformations[0].scale == [1.0, 1.0]
    assert isinstance(seq.transformations[1], ngc.TranslationTransformation)


def test_unknown_transformation_falls_back_to_custom():
    raw = [{"type": "myorg:nonlinear", "input": {"id": "a"}, "warp": [1, 2, 3]}]
    root = _tree().set_attr(
        id="img", attr=ngc.CoordinateTransformationsAttribute, value=raw
    )

    transform = root.find(id="img")[ngc.CoordinateTransformationsAttribute].root[0]
    assert isinstance(transform, ngc.CustomTransformation)
    assert transform.type == "myorg:nonlinear"
    # extra="allow" keeps the unknown field around for round-tripping.
    assert transform.warp == [1, 2, 3]
