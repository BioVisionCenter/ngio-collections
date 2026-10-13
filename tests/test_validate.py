"""Tests for L4 views & validators.

Covers the capability lenses (composable per-attribute reads), the proposal-level
`id_is_uuid` / `unique_ids` checks, the two (stale) capability validators over
bounded neighbourhoods (upward `well`⊂`plate`, reference-following `scale` vs
axes), that a node carrying several capabilities runs every validator
(composition over inheritance), and the `raise_on_error` flag.
"""

from __future__ import annotations

import pytest
from conftest import uid

import ngio_collections as ngc
from ngio_collections.graph import NodeRecord, Reference
from ngio_collections.models._paths import ZarrPath
from ngio_collections.validate import (
    get_attribute,
    has_attribute,
    id_is_uuid,
    scale_matches_axes,
    unique_ids,
    well_under_plate,
)
from ngio_collections.models.attributes import PlateAttribute, WellAttribute

VALIDATORS = (well_under_plate, scale_matches_axes)


def _plate() -> dict:
    return {"plate": {"columns": [{"id": "c1"}], "rows": [{"id": "r1"}]}}


def _well() -> dict:
    return {
        "well": {
            "column": {"type": "column", "ref": uid("c1")},
            "row": {"type": "row", "ref": uid("r1")},
        }
    }


def _axes(*names: str) -> list[dict]:
    return [{"name": n} for n in names]


def _coordinate_systems(system: str, *axes: str) -> dict:
    return {"coordinateSystems": [{"id": uid(system), "axes": _axes(*axes)}]}


def _scale(system: str, *factors: float) -> dict:
    return {
        "coordinateTransformations": [
            {
                "type": "scale",
                "output": {"type": "coordinate_system", "ref": uid(system)},
                "scale": list(factors),
            }
        ]
    }


# --------------------------------------------------------------------------- #
# Capability lenses are composable
# --------------------------------------------------------------------------- #


def test_lenses_compose_on_one_node() -> None:
    record = NodeRecord(
        type="collection", id=uid("x"), attributes={**_plate(), **_well()}
    )
    assert has_attribute(record, PlateAttribute)
    assert has_attribute(record, WellAttribute)
    well = get_attribute(record, WellAttribute)
    assert well is not None and well.column.ref == uid("c1")


# --------------------------------------------------------------------------- #
# id_is_uuid / unique_ids (proposal-level)
# --------------------------------------------------------------------------- #


def test_id_is_uuid_flags_non_uuid_ids_and_skips_references() -> None:
    stub = ngc.new_node(
        "multiscale", ref=Reference(ref=uid("x"), path=ZarrPath(href="/x.zarr"))
    )
    root = ngc.new_node("collection", id=uid("root")).add(
        ngc.new_node("multiscale", id="image"),  # pre-proposal free-form id
        ngc.new_node("multiscale", id=uid("ok").upper()),  # not canonical
        ngc.new_node("multiscale", id=uid("fine")),
        stub,
    )
    errors = ngc.validate(root, validators=(id_is_uuid,))
    assert [e.node_id for e in errors] == [("image",), (uid("ok").upper(),)]
    assert all(e.validator == "id_is_uuid" for e in errors)


def test_unique_ids_reports_each_duplicate_with_every_position() -> None:
    dup = uid("dup")
    root = ngc.new_node("collection", id=uid("root")).add(
        ngc.new_node("multiscale", id=dup),
        ngc.new_node("collection", id=uid("sub")).add(
            ngc.new_node("multiscale", id=dup),
            ngc.new_node("multiscale", id=dup),
        ),
        ngc.new_node("multiscale", id=uid("twice")),
        ngc.new_node("multiscale", id=uid("twice")),
        ngc.new_node(  # a pointer at an existing id is not a declaration
            "multiscale", ref=Reference(ref=uid("twice"), path=ZarrPath(href="/t"))
        ),
    )
    errors = unique_ids(root)
    assert [e.validator for e in errors] == ["unique_ids", "unique_ids"]
    by_id = {str(e): e for e in errors}
    assert any("3 times" in msg for msg in by_id)
    assert any("2 times" in msg for msg in by_id)
    assert {e.node_id for e in errors} == {(dup,), (uid("twice"),)}
    assert unique_ids(root.find(uid("sub"))) and len(unique_ids(root.find(uid("sub")))) == 1
    assert ngc.unique_ids(ngc.new_node("collection", id=uid("solo"))) == []


# --------------------------------------------------------------------------- #
# well ⊂ plate (upward)
# --------------------------------------------------------------------------- #


def test_well_under_plate_passes() -> None:
    plate = ngc.new_node("collection", id=uid("plate"), attributes=_plate()).add(
        ngc.new_node("collection", id=uid("A1"), attributes=_well())
    )
    assert ngc.validate(plate.find(uid("A1")), validators=VALIDATORS) == []


def test_well_without_plate_parent_is_flagged() -> None:
    orphan = ngc.new_node("collection", id=uid("root")).add(
        ngc.new_node("collection", id=uid("A1"), attributes=_well())
    )
    errors = ngc.validate(orphan.find(uid("A1")), validators=VALIDATORS)
    assert [e.validator for e in errors] == ["well_under_plate"]


# --------------------------------------------------------------------------- #
# scale vs axes (reference-following, searches self + ancestors)
# --------------------------------------------------------------------------- #


def _multiscale_with_scale(*factors: float) -> ngc.Node:
    """collection (defines `space` with 3 axes) → multiscale leaf (scale=factors)."""
    return ngc.new_node(
        "collection", id=uid("scene"), attributes=_coordinate_systems("space", "z", "y", "x")
    ).add(ngc.new_node("multiscale", id=uid("img"), attributes=_scale("space", *factors)))


def test_scale_matching_axes_passes() -> None:
    img = _multiscale_with_scale(2.0, 2.0, 2.0)  # 3 factors, 3 axes
    assert ngc.validate(img, validators=VALIDATORS) == []


def test_scale_mismatching_axes_is_flagged() -> None:
    img = _multiscale_with_scale(2.0, 2.0)  # 2 factors, 3 axes
    errors = ngc.validate(img, validators=VALIDATORS)
    assert len(errors) == 1
    assert errors[0].validator == "scale_matches_axes"
    assert errors[0].node_id == (uid("img"),)


def test_scale_resolves_coordinate_system_from_ancestor() -> None:
    # The coordinate system lives on the collection ancestor, not the multiscale.
    scene = _multiscale_with_scale(2.0, 2.0, 2.0)
    child = scene.find(uid("img"))
    assert child is not None and not child.has(ngc.CoordinateSystemsAttribute)
    assert ngc.validate(child, validators=VALIDATORS) == []


@pytest.mark.xfail(
    strict=True, reason="capability validators are not ported to proposal traits"
)
def test_scale_matches_axes_reads_proposal_shaped_multiscale() -> None:
    # Proposal shape: `coordinate_systems` and `scales[*].coordinate_transformations`
    # in the multiscale body. The stale validator does not see these keys.
    img = ngc.new_node(
        "multiscale",
        id=uid("img"),
        attributes={
            "coordinate_systems": [{"id": uid("space"), "axes": _axes("z", "y", "x")}],
            "scales": [
                {
                    "id": uid("s0"),
                    "path": {"type": "zarr", "format": "relative", "href": "./s0"},
                    "coordinate_transformations": [
                        {
                            "type": "scale",
                            "scale": [2.0, 2.0],  # 2 factors, 3 axes
                            "output": {"type": "coordinate_system", "ref": uid("space")},
                        }
                    ],
                }
            ],
        },
    )
    assert [e.validator for e in ngc.validate(img, validators=VALIDATORS)] == [
        "scale_matches_axes"
    ]


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
    node = ngc.new_node("multiscale", id=uid("x"), attributes=bad)
    found = {e.validator for e in ngc.validate(node, validators=VALIDATORS)}
    assert found == {well_under_plate.__name__, scale_matches_axes.__name__}


# --------------------------------------------------------------------------- #
# raise_on_error re-raises the first failure instead of collecting
# --------------------------------------------------------------------------- #


def test_raise_on_error_reraises_first_failure() -> None:
    orphan = ngc.new_node("collection", id=uid("root")).add(
        ngc.new_node("collection", id=uid("A1"), attributes=_well())
    )
    with pytest.raises(ngc.ValidationError) as exc_info:
        ngc.validate(orphan.find(uid("A1")), validators=VALIDATORS, raise_on_error=True)
    assert exc_info.value.validator == "well_under_plate"
    assert exc_info.value.node_id == (uid("A1"),)
