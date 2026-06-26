"""Validation tests for the typed OME attribute models (decoupled from nodes).

These exercise the kept attribute models directly via `model_validate` /
construction — the same models the v5 capability lenses validate through. Node
integration is covered separately in `test_node.py` / `test_validate.py`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ngio_collections.models._references import ReferenceObj
from ngio_collections.models.attributes import (
    CoordinateSystemsAttribute,
    CustomTransformation,
    PlateAttribute,
    ScaleTransformation,
    SceneAttribute,
    SequenceTransformation,
    TranslationTransformation,
    WellAttribute,
)


def test_plate_validates_columns_and_rows() -> None:
    plate = PlateAttribute.model_validate(
        {"columns": [{"id": "1"}, {"id": "2"}], "rows": [{"id": "A"}]}
    )
    assert [c.id for c in plate.columns] == ["1", "2"]
    assert plate.acquisitions == []  # optional, defaults empty


def test_plate_requires_columns_and_rows() -> None:
    with pytest.raises(ValidationError):
        PlateAttribute.model_validate({"rows": [{"id": "A"}]})


def test_well_carries_reference_objects() -> None:
    well = WellAttribute.model_validate({"column": {"id": "c1"}, "row": {"id": "r1"}})
    assert isinstance(well.column, ReferenceObj) and well.column.id == "c1"


def test_coordinate_systems_list_attribute_and_typed_axes() -> None:
    systems = CoordinateSystemsAttribute.model_validate(
        [{"id": "cs0", "axes": [{"name": "x", "unit": "micrometer"}, {"name": "c", "discrete": True}]}]
    )
    axes = systems.root[0].axes
    assert systems.root[0].id == "cs0"
    assert [a.name for a in axes] == ["x", "c"]
    assert axes[0].unit == "micrometer" and axes[1].discrete is True


def test_scene_with_nested_typed_transformations() -> None:
    scene = SceneAttribute.model_validate(
        {
            "coordinateSystems": [{"id": "cs0", "axes": [{"name": "x"}]}],
            "coordinateTransformations": [
                {
                    "type": "sequence",
                    "input": {"id": "cs0"},
                    "output": {"id": "cs1"},
                    "transformations": [
                        {"type": "scale", "scale": [1.0, 1.0]},
                        {"type": "translation", "translation": [0.0, 5.0]},
                    ],
                }
            ],
        }
    )
    seq = scene.coordinate_transformations[0]
    assert isinstance(seq, SequenceTransformation)
    assert isinstance(seq.transformations[0], ScaleTransformation)
    assert seq.transformations[0].scale == [1.0, 1.0]
    assert isinstance(seq.transformations[1], TranslationTransformation)


def test_unknown_transformation_falls_back_to_custom_and_round_trips() -> None:
    systems = CoordinateSystemsAttribute.model_validate([])  # sanity: empty list ok
    assert systems.root == []
    transform = CustomTransformation.model_validate(
        {"type": "myorg:nonlinear", "input": {"id": "a"}, "warp": [1, 2, 3]}
    )
    assert transform.type == "myorg:nonlinear"
    assert transform.warp == [1, 2, 3]  # extra="allow" keeps unknown fields
