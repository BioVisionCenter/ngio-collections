"""The built-in example validators and the tuple that bundles them.

These demonstrate the two neighbourhood shapes a validator reads through the
`Node` handle:

- `well_under_plate` reads *up* one level (a node with a `well` capability must
  sit under a node with a `plate` capability).
- `scale_matches_axes` follows a *reference*: a `scale` transform's factor count
  must match the axis count of the coordinate system it points at, searched on
  the node itself and its ancestors.

Each is a plain callable that `raise`s `ValidationError` on a problem and returns
otherwise; callers pass the ones they want explicitly
(`ngc.validate(view, validators=(ngc.well_under_plate, ngc.scale_matches_axes))`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

from ngio_collections.models.attributes import (
    CoordinateSystem,
    CoordinateSystemsAttribute,
    CoordinateTransformationsAttribute,
    PlateAttribute,
    SceneAttribute,
    ScaleTransformation,
    WellAttribute,
)
from ngio_collections.validate._engine import ValidationError

if TYPE_CHECKING:
    from ngio_collections.api._node import Node


def well_under_plate(node: Node) -> None:
    """A node carrying `well` must be a child of a node carrying `plate`."""
    if not node.has(WellAttribute):
        return
    parent = node.parent()
    if parent is None or not parent.has(PlateAttribute):
        raise ValidationError(
            "a node with a `well` attribute must be a child of a node with a "
            "`plate` attribute"
        )


def scale_matches_axes(node: Node) -> None:
    """A `scale` transform's factor count must match its coordinate system's axes."""
    if not node.has(CoordinateTransformationsAttribute):
        return
    for transform in node[CoordinateTransformationsAttribute].root:
        if not isinstance(transform, ScaleTransformation) or transform.scale is None:
            continue
        ref = transform.output or transform.input
        if ref is None:
            continue
        system = _find_coordinate_system(node, ref.id)
        if system is None:
            continue  # unresolved system: a referential check's concern, not this one
        if len(transform.scale) != len(system.axes):
            raise ValidationError(
                f"scale transform has {len(transform.scale)} factor(s) but "
                f"coordinate system {system.id!r} has {len(system.axes)} axis/axes"
            )


def _find_coordinate_system(node: Node, system_id: str) -> CoordinateSystem | None:
    """Search the focus node and its ancestors for coordinate system `system_id`."""
    for scope in _self_and_ancestors(node):
        system = _coordinate_system_in(scope, system_id)
        if system is not None:
            return system
    return None


def _self_and_ancestors(node: Node) -> Iterator[Node]:
    """Yield `node` then each of its ancestors up to the root."""
    yield node
    yield from node.ancestors()


def _coordinate_system_in(node: Node, system_id: str) -> CoordinateSystem | None:
    """Return the coordinate system `system_id` defined on `node`, if any."""
    systems: list[CoordinateSystem] = []
    coordinate_systems = node.get_attr(CoordinateSystemsAttribute)
    if coordinate_systems is not None:
        systems.extend(coordinate_systems.root)
    scene = node.get_attr(SceneAttribute)
    if scene is not None and scene.coordinate_systems:
        systems.extend(scene.coordinate_systems)
    return next((s for s in systems if s.id == system_id), None)
