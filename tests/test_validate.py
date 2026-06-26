"""Tests for L4 views & validators.

Covers the capability lenses (composable per-attribute reads), the two example
validators over bounded neighbourhoods (upward `well`⊂`plate`, reference-following
`scale` vs axes), and that a node carrying several capabilities runs every
applicable validator (composition over inheritance).
"""

from __future__ import annotations

from ngio_collections.graph import ROOT, NodeTree, NodeRecord
from ngio_collections.validate import (
    Context,
    get_attribute,
    has_attribute,
    register_builtins,
    validate,
    validate_tree,
)
from ngio_collections.models.attributes import (
    CoordinateSystemsAttribute,
    PlateAttribute,
    WellAttribute,
)

REG = register_builtins()


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
# well ⊂ plate (upward, Scope(ancestors=1))
# --------------------------------------------------------------------------- #


def test_well_under_plate_passes() -> None:
    c = NodeTree.of(NodeRecord(type="collection", id="plate", attributes=_plate(), children=()))
    c, well = c.add_child(ROOT, NodeRecord(type="collection", id="A1", attributes=_well()))
    assert validate(c, well, registry=REG) == []


def test_well_without_plate_parent_is_flagged() -> None:
    c = NodeTree.of(NodeRecord(type="collection", id="root", children=()))
    c, well = c.add_child(ROOT, NodeRecord(type="collection", id="A1", attributes=_well()))
    issues = validate(c, well, registry=REG)
    assert [i.validator for i in issues] == ["well-under-plate"]


# --------------------------------------------------------------------------- #
# scale vs axes (reference-following, Scope(ancestors=None, refs=True))
# --------------------------------------------------------------------------- #


def _multiscale_with_scale(*factors: float) -> NodeTree:
    """multiscale (defines `space` with 3 axes) → singlescale (scale=factors)."""
    c = NodeTree.of(
        NodeRecord(
            type="multiscale",
            id="img",
            attributes=_coordinate_systems("space", "z", "y", "x"),
            children=(),
        )
    )
    c, _ = c.add_child(
        ROOT, NodeRecord(type="singlescale", id="0", attributes=_scale("space", *factors))
    )
    return c


def test_scale_matching_axes_passes() -> None:
    c = _multiscale_with_scale(2.0, 2.0, 2.0)  # 3 factors, 3 axes
    assert validate_tree(c, registry=REG) == []


def test_scale_mismatching_axes_is_flagged() -> None:
    c = _multiscale_with_scale(2.0, 2.0)  # 2 factors, 3 axes
    issues = validate_tree(c, registry=REG)
    assert len(issues) == 1
    assert issues[0].validator == "scale-matches-axes"
    assert issues[0].node_id == ("0",)


def test_scale_resolves_coordinate_system_from_ancestor() -> None:
    # The coordinate system lives on the multiscale ancestor, not the singlescale.
    c = _multiscale_with_scale(2.0, 2.0, 2.0)
    (child,) = c.children_ids(ROOT)
    # the coordinate system is defined on the ancestor, not on the child itself
    assert not has_attribute(c.record(child), CoordinateSystemsAttribute)
    assert validate(c, child, registry=REG) == []


# --------------------------------------------------------------------------- #
# Composition: one node, several capabilities -> several validators
# --------------------------------------------------------------------------- #


def test_node_with_two_capabilities_runs_both_validators() -> None:
    # A node that is both a `well` (no plate parent) AND carries a bad scale
    # transform against a coordinate system it defines itself.
    bad = {**_well(), **_coordinate_systems("space", "z", "y", "x"), **_scale("space", 2.0, 2.0)}
    c = NodeTree.of(NodeRecord(type="collection", id="root", children=()))
    c, node = c.add_child(ROOT, NodeRecord(type="multiscale", id="x", attributes=bad))

    ctx = Context(c, node)
    applicable = {v.name for v in REG.applicable(ctx)}
    assert applicable == {"well-under-plate", "scale-matches-axes"}

    found = {i.validator for i in validate(c, node, registry=REG)}
    assert found == {"well-under-plate", "scale-matches-axes"}
