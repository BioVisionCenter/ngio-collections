"""Built-in attribute models through the typed attrs view."""

import pytest
from pydantic import ValidationError

import ome_zarr_collections as ozc
from ome_zarr_collections.models import (
    AcquisitionObj,
    ColumnObj,
    LabelObj,
    RowObj,
)


def _node() -> ozc.BaseNode:
    return ozc.BaseNode(type="x", id="n1", name="n1")


def test_plate_attribute_round_trip():
    plate = ozc.PlateAttribute(
        acquisitions=[AcquisitionObj(id="acq1", name="Acquisition 1")],
        columns=[ColumnObj(id="col1", name="1")],
        rows=[RowObj(id="rowA", name="A")],
    )
    node = _node()
    node.attrs[ozc.PlateAttribute] = plate
    assert ozc.PlateAttribute in node.attrs
    assert node.attrs[ozc.PlateAttribute] == plate


def test_plate_requires_columns_and_rows():
    with pytest.raises(ValidationError):
        ozc.PlateAttribute(acquisitions=[])


def test_well_attribute_stored_spec_shaped():
    well = ozc.WellAttribute(
        column=ozc.ReferenceObj(id="col1"), row=ozc.ReferenceObj(id="rowA")
    )
    node = _node()
    node.attrs[ozc.WellAttribute] = well
    # exclude_none keeps the stored dict spec-shaped (no "path": null).
    assert node.attributes["well"] == {
        "column": {"id": "col1"},
        "row": {"id": "rowA"},
    }
    assert node.attrs[ozc.WellAttribute] == well


def test_acquisition_attribute_is_a_reference():
    node = _node()
    node.attrs[ozc.AcquisitionAttribute] = ozc.AcquisitionAttribute(id="acq1")
    assert node.attributes["acquisition"] == {"id": "acq1"}


def test_labels_attribute_uses_camel_case_aliases():
    labels = ozc.LabelsAttribute(
        label_attributes=[LabelObj(label_value=1, color=[255, 0, 0, 255])],
        source=[ozc.ReferenceObj(id="raw")],
    )
    node = _node()
    node.attrs[ozc.LabelsAttribute] = labels
    stored = node.attributes["labels"]
    assert stored["labelAttributes"] == [{"labelValue": 1, "color": [255, 0, 0, 255]}]
    assert node.attrs[ozc.LabelsAttribute] == labels


@pytest.mark.parametrize("color", [[255, 0, 0], [256, 0, 0, 0], [-1, 0, 0, 0]])
def test_label_color_must_be_four_uint8(color):
    with pytest.raises(ValidationError, match="color"):
        LabelObj(label_value=1, color=color)


def test_coordinate_systems_list_attribute_round_trip():
    systems = ozc.CoordinateSystemsAttribute(
        [ozc.CoordinateSystem(id="physical", axes=[{"name": "x", "type": "space"}])]
    )
    node = _node()
    node.attrs[ozc.CoordinateSystemsAttribute] = systems
    assert node.attributes["coordinateSystems"] == [
        {"id": "physical", "axes": [{"name": "x", "type": "space"}]}
    ]
    loaded = node.attrs.get(ozc.CoordinateSystemsAttribute)
    assert loaded is not None
    assert loaded.root[0].id == "physical"


def test_scene_attribute_round_trip():
    scene = ozc.SceneAttribute(
        coordinate_systems=[
            ozc.CoordinateSystem(id="world", axes=[{"name": "x", "type": "space"}])
        ],
        coordinate_transformations=[
            ozc.CoordinateTransformation.model_validate(
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
    node.attrs[ozc.SceneAttribute] = scene
    stored = node.attributes["scene"]
    assert stored["coordinateSystems"][0]["id"] == "world"
    # Extra transform fields (translation) survive the round trip.
    assert stored["coordinateTransformations"][0]["translation"] == [0, 0, 100]
    assert node.attrs[ozc.SceneAttribute] == scene
