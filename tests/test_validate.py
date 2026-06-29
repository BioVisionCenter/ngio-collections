"""Tests for L4 views & validators.

Covers the capability lenses (composable per-attribute reads), the two example
validators over bounded neighbourhoods (upward `well`⊂`plate`, reference-following
`scale` vs axes), that a node carrying several capabilities runs every validator
(composition over inheritance), and the `raise_on_error` flag.
"""

from __future__ import annotations

import pytest

import ngio_collections as ngc
from ngio_collections.graph import NodeRecord
from ngio_collections.validate import (
    get_attribute,
    has_attribute,
    scale_matches_axes,
    well_under_plate,
)
from ngio_collections.models.attributes import PlateAttribute, WellAttribute

VALIDATORS = (well_under_plate, scale_matches_axes)


def _plate() -> dict:
    return {"plate": {"columns": [{"id": "c1"}], "rows": [{"id": "r1"}]}}


def _well() -> dict:
    return {"well": {"column": {"id": "c1"}, "row": {"id": "r1"}}}


def _axes(*names: str) -> list[dict]:
    return [{"name": n} for n in names]


def _coordinate_systems(system_id: str, *axes: str) -> dict:
    return {"coordinateSystems": [{"id": system_id, "axes": _axes(*axes)}]}


def _scale(system_id: str, *factors: float) -> dict:
    return {
        "coordinateTransformations": [
            {"type": "scale", "output": {"id": system_id}, "scale": list(factors)}
        ]
    }


# --------------------------------------------------------------------------- #
# Capability lenses are composable
# --------------------------------------------------------------------------- #


def test_lenses_compose_on_one_node() -> None:
    record = NodeRecord(type="collection", attributes={**_plate(), **_well()})
    assert has_attribute(record, PlateAttribute)
    assert has_attribute(record, WellAttribute)
    well = get_attribute(record, WellAttribute)
    assert well is not None and well.column.id == "c1"


# --------------------------------------------------------------------------- #
# well ⊂ plate (upward)
# --------------------------------------------------------------------------- #


def test_well_under_plate_passes() -> None:
    plate = ngc.new_node("collection", id="plate", attributes=_plate()).add(
        ngc.new_node("collection", id="A1", attributes=_well())
    )
    assert ngc.validate(plate.find("A1"), validators=VALIDATORS) == []


def test_well_without_plate_parent_is_flagged() -> None:
    orphan = ngc.new_node("collection", id="root").add(
        ngc.new_node("collection", id="A1", attributes=_well())
    )
    errors = ngc.validate(orphan.find("A1"), validators=VALIDATORS)
    assert [e.validator for e in errors] == ["well_under_plate"]


# --------------------------------------------------------------------------- #
# scale vs axes (reference-following, searches self + ancestors)
# --------------------------------------------------------------------------- #


def _multiscale_with_scale(*factors: float) -> ngc.Node:
    """multiscale (defines `space` with 3 axes) → singlescale (scale=factors)."""
    return ngc.new_node(
        "multiscale", id="img", attributes=_coordinate_systems("space", "z", "y", "x")
    ).add(ngc.new_node("singlescale", id="0", attributes=_scale("space", *factors)))


def test_scale_matching_axes_passes() -> None:
    img = _multiscale_with_scale(2.0, 2.0, 2.0)  # 3 factors, 3 axes
    assert ngc.validate(img, validators=VALIDATORS) == []


def test_scale_mismatching_axes_is_flagged() -> None:
    img = _multiscale_with_scale(2.0, 2.0)  # 2 factors, 3 axes
    errors = ngc.validate(img, validators=VALIDATORS)
    assert len(errors) == 1
    assert errors[0].validator == "scale_matches_axes"
    assert errors[0].node_id == ("0",)


def test_scale_resolves_coordinate_system_from_ancestor() -> None:
    # The coordinate system lives on the multiscale ancestor, not the singlescale.
    img = _multiscale_with_scale(2.0, 2.0, 2.0)
    child = img.find("0")
    assert child is not None and not child.has(ngc.CoordinateSystemsAttribute)
    assert ngc.validate(child, validators=VALIDATORS) == []


# --------------------------------------------------------------------------- #
# Composition: one node, several capabilities -> several validators
# --------------------------------------------------------------------------- #


def test_node_with_two_capabilities_runs_both_validators() -> None:
    # A node that is both a `well` (no plate parent) AND carries a bad scale
    # transform against a coordinate system it defines itself.
    bad = {
        **_well(),
        **_coordinate_systems("space", "z", "y", "x"),
        **_scale("space", 2.0, 2.0),
    }
    node = ngc.new_node("multiscale", id="x", attributes=bad)
    found = {e.validator for e in ngc.validate(node, validators=VALIDATORS)}
    assert found == {well_under_plate.__name__, scale_matches_axes.__name__}


# --------------------------------------------------------------------------- #
# raise_on_error re-raises the first failure instead of collecting
# --------------------------------------------------------------------------- #


def test_raise_on_error_reraises_first_failure() -> None:
    orphan = ngc.new_node("collection", id="root").add(
        ngc.new_node("collection", id="A1", attributes=_well())
    )
    with pytest.raises(ngc.ValidationError) as exc_info:
        ngc.validate(orphan.find("A1"), validators=VALIDATORS, raise_on_error=True)
    assert exc_info.value.validator == "well_under_plate"
    assert exc_info.value.node_id == ("A1",)
