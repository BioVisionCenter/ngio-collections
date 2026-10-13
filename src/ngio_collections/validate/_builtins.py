"""The built-in validators.

Proposal-level checks, current:

- `id_is_uuid` — every declaration's `id` is a canonical lowercase UUID.
- `unique_ids` — a tree-level check (not a per-node validator): no id is
  declared twice in the subtree. Reports every duplicate with all its `NodeId`s.

Capability checks, **stale**: `well_under_plate` and `scale_matches_axes` read
the pre-proposal camelCase attribute keys (`well`, `plate`, `coordinateSystems`,
`coordinateTransformations`) through the typed attribute models. They still run
on data written with those keys, but the proposal's traits (`coordinate_systems`,
`scales[*].coordinate_transformations`) are not read; porting them is a
follow-up. They demonstrate the two neighbourhood shapes a validator reads
through the `Node` handle: up one level, and following a reference.

Each per-node validator is a plain callable that `raise`s `ValidationError` on
a problem and returns otherwise; callers pass the ones they want explicitly
(`ngc.validate(view, validators=(ngc.id_is_uuid, ngc.well_under_plate))`).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterator

from ngio_collections.graph import NodeId
from ngio_collections.models._references import UUID_PATTERN
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

_UUID = re.compile(UUID_PATTERN)


def id_is_uuid(node: Node) -> None:
    """A declaration's `id` must be a canonical lowercase hyphenated UUID."""
    if node.is_reference:
        return  # a reference declares no id
    id = node.id
    if id is None or _UUID.fullmatch(id) is None:
        raise ValidationError(f"id {id!r} is not a canonical lowercase UUID")


def unique_ids(root: Node) -> list[ValidationError]:
    """Report every id declared more than once in `root`'s subtree.

    A tree-level check: one walk buckets the declarations by id; each duplicate
    yields a single `ValidationError` naming every `NodeId` that declares it
    (`node_id` is the first occurrence). References are pointers, not
    declarations, and do not count.
    """
    seen: dict[str, list[NodeId]] = {}
    for node in root.walk():
        if node.id is not None:
            seen.setdefault(node.id, []).append(node.node_id)
    errors: list[ValidationError] = []
    for id, node_ids in seen.items():
        if len(node_ids) < 2:
            continue
        where = ", ".join("/".join(n) or "<root>" for n in node_ids)
        error = ValidationError(f"id {id!r} is declared {len(node_ids)} times: {where}")
        error.node_id = node_ids[0]
        error.validator = unique_ids.__name__
        errors.append(error)
    return errors


def well_under_plate(node: Node) -> None:
    """A node carrying `well` must be a child of a node carrying `plate`.

    Stale: reads the pre-proposal `well` / `plate` attribute keys.
    """
    if not node.has(WellAttribute):
        return
    parent = node.parent()
    if parent is None or not parent.has(PlateAttribute):
        raise ValidationError(
            "a node with a `well` attribute must be a child of a node with a "
            "`plate` attribute"
        )


def scale_matches_axes(node: Node) -> None:
    """A `scale` transform's factor count must match its coordinate system's axes.

    Stale: reads the pre-proposal camelCase `coordinateTransformations` /
    `coordinateSystems` keys, not the proposal's `scales[*]` traits.
    """
    if not node.has(CoordinateTransformationsAttribute):
        return
    for transform in node[CoordinateTransformationsAttribute].root:
        if not isinstance(transform, ScaleTransformation) or transform.scale is None:
            continue
        ref = transform.output or transform.input
        if ref is None:
            continue
        system = _find_coordinate_system(node, ref.ref)
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
