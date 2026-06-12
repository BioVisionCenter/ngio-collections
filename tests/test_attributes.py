"""Built-in attribute models through the typed attrs view."""

import pytest
from pydantic import ValidationError

import ngio_collections as ngc
from ngio_collections.models import (
    AcquisitionObj,
    ColumnObj,
    LabelObj,
    RowObj,
)


def _node() -> ngc.BaseNode:
    return ngc.BaseNode(type="x", id="n1", name="n1")


def test_plate_attribute_round_trip():
    plate = ngc.PlateAttribute(
        acquisitions=[AcquisitionObj(id="acq1", name="Acquisition 1")],
        columns=[ColumnObj(id="col1", name="1")],
        rows=[RowObj(id="rowA", name="A")],
    )
    node = _node()
    node.attrs[ngc.PlateAttribute] = plate
    assert ngc.PlateAttribute in node.attrs
    assert node.attrs[ngc.PlateAttribute] == plate


def test_plate_requires_columns_and_rows():
    with pytest.raises(ValidationError):
        ngc.PlateAttribute(acquisitions=[])


def test_well_attribute_stored_spec_shaped():
    well = ngc.WellAttribute(
        column=ngc.ReferenceObj(id="col1"), row=ngc.ReferenceObj(id="rowA")
    )
    node = _node()
    node.attrs[ngc.WellAttribute] = well
    # exclude_none keeps the stored dict spec-shaped (no "path": null).
    assert node.attributes["well"] == {
        "column": {"id": "col1"},
        "row": {"id": "rowA"},
    }
    assert node.attrs[ngc.WellAttribute] == well


def test_acquisition_attribute_is_a_reference():
    node = _node()
    node.attrs[ngc.AcquisitionAttribute] = ngc.AcquisitionAttribute(id="acq1")
    assert node.attributes["acquisition"] == {"id": "acq1"}


def test_labels_attribute_uses_camel_case_aliases():
    labels = ngc.LabelsAttribute(
        label_attributes=[LabelObj(label_value=1, color=[255, 0, 0, 255])],
        source=[ngc.ReferenceObj(id="raw")],
    )
    node = _node()
    node.attrs[ngc.LabelsAttribute] = labels
    stored = node.attributes["labels"]
    assert stored["labelAttributes"] == [{"labelValue": 1, "color": [255, 0, 0, 255]}]
    assert node.attrs[ngc.LabelsAttribute] == labels


@pytest.mark.parametrize("color", [[255, 0, 0], [256, 0, 0, 0], [-1, 0, 0, 0]])
def test_label_color_must_be_four_uint8(color):
    with pytest.raises(ValidationError, match="color"):
        LabelObj(label_value=1, color=color)


def test_coordinate_systems_list_attribute_round_trip():
    systems = ngc.CoordinateSystemsAttribute(
        [ngc.CoordinateSystem(id="physical", axes=[{"name": "x", "type": "space"}])]
    )
    node = _node()
    node.attrs[ngc.CoordinateSystemsAttribute] = systems
    assert node.attributes["coordinateSystems"] == [
        {"id": "physical", "axes": [{"name": "x", "type": "space"}]}
    ]
    loaded = node.attrs.get(ngc.CoordinateSystemsAttribute)
    assert loaded is not None
    assert loaded.root[0].id == "physical"


def test_scene_attribute_round_trip():
    scene = ngc.SceneAttribute(
        coordinate_systems=[
            ngc.CoordinateSystem(id="world", axes=[{"name": "x", "type": "space"}])
        ],
        coordinate_transformations=[
            ngc.CoordinateTransformation.model_validate(
                {
                    "type": "translation",
                    "translation": [0, 0, 100],
                    "input": {
                        "id": "physical",
                        "path": {"type": "zarr", "path": "./tile_0.zarr"},
                    },
                    "output": {"id": "world"},
                }
            )
        ],
    )
    node = _node()
    node.attrs[ngc.SceneAttribute] = scene
    stored = node.attributes["scene"]
    assert stored["coordinateSystems"][0]["id"] == "world"
    # Extra transform fields (translation) survive the round trip.
    assert stored["coordinateTransformations"][0]["translation"] == [0, 0, 100]
    assert node.attrs[ngc.SceneAttribute] == scene
