"""RECOMMENDED validators: the rules of the revision's recommended-tier traits.

HCS and labels are deferred to sub-RFCs (RFC-8 revision 1 §11), so these encode
the rules the revision's examples imply and §3.1's `applies_to` constraint:

- `well_under_plate` reads *up* one level: a `well` sits under a `plate`.
- `plate_children_are_wells` reads *down* one level: a plate's children are
  collections carrying `well`.
- `trait_applies_to`: each built-in trait sits on a node type it applies to.
- `scale_matches_axes`: a `scale` transform's factor count matches the axis
  count of the coordinate system it maps into, within the same multiscale (or
  the same `scene`).
- `labels_source_resolves`: a `labels` trait's sources are multiscales.

Each is a plain callable that `raise`s `ValidationError` on a problem and returns
otherwise; callers pass the ones they want explicitly or use the bundles.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from ngio_collections.models._multiscale import CoordinateSystem, MultiscaleFields
from ngio_collections.models._transformation import (
    CoordinateTransformation,
    ScaleTransformation,
)
from ngio_collections.models.traits import (
    AcquisitionTrait,
    BaseTrait,
    LabelsTrait,
    PlateTrait,
    SceneTrait,
    WellTrait,
)
from ngio_collections.validate._engine import ValidationError

if TYPE_CHECKING:
    from ngio_collections.api._node import Node

_BUILTIN_TRAITS: tuple[type[BaseTrait], ...] = (
    SceneTrait,
    PlateTrait,
    WellTrait,
    AcquisitionTrait,
    LabelsTrait,
)


def well_under_plate(node: Node) -> None:
    """A node carrying `well` must be a child of a node carrying `plate`."""
    if not node.has_trait(WellTrait):
        return
    parent = node.parent()
    if parent is None or not parent.has_trait(PlateTrait):
        raise ValidationError(
            "a node with a `well` trait must be a child of a node with a `plate` trait"
        )


def plate_children_are_wells(node: Node) -> None:
    """Every child of a node carrying `plate` is a collection carrying `well`."""
    if not node.has_trait(PlateTrait):
        return
    for child in node.children():
        if child.type != "collection" or not child.has_trait(WellTrait):
            raise ValidationError(
                f"child {child.id!r} of a plate is not a collection with a `well` trait"
            )


def trait_applies_to(node: Node) -> None:
    """Each built-in trait sits on a node type it applies to (§3.1)."""
    for trait in _BUILTIN_TRAITS:
        if (
            node.has_trait(trait)
            and trait.applies_to
            and node.type not in trait.applies_to
        ):
            raise ValidationError(
                f"trait {trait.trait_type()!r} applies to {sorted(trait.applies_to)}, "
                f"not to a {node.type!r} node"
            )


def _check_scales(
    transforms: Iterable[CoordinateTransformation],
    systems: Iterable[CoordinateSystem],
) -> None:
    """Raise if a `scale` transform's factor count mismatches its output system."""
    by_id = {s.id: s for s in systems}
    for transform in transforms:
        if not isinstance(transform, ScaleTransformation) or transform.scale is None:
            continue
        ref = transform.output or transform.input
        if ref is None or ref.path is not None:
            continue
        system = by_id.get(ref.ref)
        if system is None:
            continue  # a dangling reference is `references_resolve`'s concern
        if len(transform.scale) != len(system.axes):
            raise ValidationError(
                f"scale transform has {len(transform.scale)} factor(s) but "
                f"coordinate system {system.id!r} has {len(system.axes)} axis/axes"
            )


def scale_matches_axes(node: Node) -> None:
    """A `scale` transform's factor count must match its coordinate system's axes."""
    if node.type == "multiscale" and node.fields:
        try:
            fields = MultiscaleFields.model_validate(dict(node.fields))
        except Exception:
            return  # malformed fields are `multiscale_is_complete`'s concern
        for scale in fields.scales:
            _check_scales(scale.coordinate_transformations, fields.coordinate_systems)
    scene = node.get_trait(SceneTrait)
    if scene is not None:
        _check_scales(scene.coordinate_transformations, scene.coordinate_systems)


def labels_source_resolves(node: Node) -> None:
    """A `labels` trait's `source` entries are references to multiscales."""
    labels = node.get_trait(LabelsTrait)
    if labels is None:
        return
    for source in labels.source:
        if source.type != "multiscale":
            raise ValidationError(
                f"labels source {source.ref!r} has type {source.type!r}, "
                "expected 'multiscale'"
            )
        if source.path is not None:
            continue
        keys = node.tree.find(source.ref)
        if not any(node.tree.record(k).type == "multiscale" for k in keys):
            raise ValidationError(
                f"labels source {source.ref!r} is not a multiscale in this document"
            )


RECOMMENDED_VALIDATORS = (
    well_under_plate,
    plate_children_are_wells,
    trait_applies_to,
    scale_matches_axes,
    labels_source_resolves,
)
"""The checks for the revision's recommended-tier traits."""
