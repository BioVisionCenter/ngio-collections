"""RECOMMENDED validators: the rules of the revision's recommended-tier traits.

HCS and labels are deferred to sub-RFCs (RFC-8 revision 2, "Future
possibilities"), so these encode the rules the provisional traits imply and
their `applies_to` constraint:

- `well_under_plate` reads *up* one level: a `well` sits under a `plate`.
- `plate_children_are_wells` reads *down* one level: a plate's children are
  collections carrying `well`.
- `trait_applies_to`: each built-in trait sits on a node type it applies to.
- `scale_matches_axes`: every per-axis vector has as many entries as the
  coordinate system it relates to: a multiscale's array downsampling factors
  and offsets against the axis count of its coordinate systems, and a `scale`
  transform's factors against the system it maps into (multiscale-level
  transformations and `scene` traits alike).
- `labels_source_resolves`: a `labels` trait's sources are multiscales.
- `manifest_lists_downstream`: in a resolved view, a document's manifest also
  lists the extensions declared by the documents it points at (upstream
  "Extension manifest", a SHOULD).

Each is a plain callable that `raise`s `ValidationError` on a problem and returns
otherwise; callers pass the ones they want explicitly or use the bundles.
`well_under_plate`, `plate_children_are_wells` and `manifest_lists_downstream`
run without pydantic; the other three read through the pydantic value models
and import them lazily (the `validate` extra).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from ngio_collections._optional import require_pydantic
from ngio_collections.resolve import document_records
from ngio_collections.validate._engine import ValidationError

if TYPE_CHECKING:
    from ngio_collections.api._node import Node
    from ngio_collections.models._multiscale import CoordinateSystem, MultiscaleFields
    from ngio_collections.models._transformation import CoordinateTransformation


def well_under_plate(node: Node) -> None:
    """A node carrying `well` must be a child of a node carrying `plate`."""
    if not node.has_trait("well"):
        return
    parent = node.parent()
    if parent is None or not parent.has_trait("plate"):
        raise ValidationError(
            "a node with a `well` trait must be a child of a node with a `plate` trait"
        )


def plate_children_are_wells(node: Node) -> None:
    """Every child of a node carrying `plate` is a collection carrying `well`."""
    if not node.has_trait("plate"):
        return
    for child in node.children():
        if child.type != "collection" or not child.has_trait("well"):
            raise ValidationError(
                f"child {child.id!r} of a plate is not a collection with a `well` trait"
            )


def trait_applies_to(node: Node) -> None:
    """Each built-in trait sits on a node type it applies to."""
    require_pydantic("trait_applies_to")
    from ngio_collections.models.traits import (
        AcquisitionTrait,
        LabelsTrait,
        PlateTrait,
        SceneTrait,
        WellTrait,
    )

    builtin = (SceneTrait, PlateTrait, WellTrait, AcquisitionTrait, LabelsTrait)
    for trait in builtin:
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
    from ngio_collections.models._transformation import ScaleTransformation

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


def _check_arrays(fields: MultiscaleFields) -> None:
    """Raise if an array's downsampling vectors mismatch the axis count.

    The dimensionality is the axis count the multiscale's coordinate systems
    agree on; when they disagree there is no single answer and nothing is checked.
    """
    ndim = {len(system.axes) for system in fields.coordinate_systems}
    if len(ndim) != 1:
        return
    (n,) = ndim
    for index, array in enumerate(fields.arrays):
        for transform in array.downsamplingTransformations or ():
            vector = getattr(transform, transform.type)
            if len(vector) != n:
                raise ValidationError(
                    f"array {index} has a {transform.type!r} "
                    f"downsampling vector of {len(vector)} entries but the "
                    f"multiscale has {n} axis/axes"
                )


def scale_matches_axes(node: Node) -> None:
    """Per-axis vectors (downsampling, `scale` transforms) match the axis count."""
    require_pydantic("scale_matches_axes")
    from ngio_collections.models._multiscale import MultiscaleFields
    from ngio_collections.models.traits import SceneTrait

    if node.type == "multiscale" and node.fields:
        try:
            fields = MultiscaleFields.model_validate(dict(node.fields))
        except Exception:
            return  # malformed fields are `multiscale_is_complete`'s concern
        _check_arrays(fields)
        _check_scales(fields.coordinate_transformations, fields.coordinate_systems)
    try:
        scene = node.get_trait(SceneTrait)
    except Exception as exc:  # pydantic.ValidationError
        raise ValidationError(f"scene trait does not validate: {exc}") from exc
    if scene is not None:
        _check_scales(scene.coordinate_transformations, scene.coordinate_systems)


def labels_source_resolves(node: Node) -> None:
    """A `labels` trait's `source` entries are references to multiscales."""
    require_pydantic("labels_source_resolves")
    from ngio_collections.models.traits import LabelsTrait

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


def manifest_lists_downstream(node: Node) -> None:
    """A document's manifest lists the extensions of the documents it points at.

    Runs on the node that opens a document, in a resolved view (where the
    manifests of the target documents are known). Each directly referenced
    document is compared; documents further down are checked against their own
    parent in turn.
    """
    tree = node.tree
    parent = node.parent()
    url = node.document_url
    if tree.mode != "resolved" or url is None:
        return
    if parent is not None and parent.document_url == url:
        return
    listed = {entry.get("id") for entry in tree.manifests.get(url, ())}
    missing: set[str] = set()
    for key in document_records(tree, node.node_id):
        record = tree.record(key)
        if key == node.node_id or record.edge is None or record.origin_url is None:
            continue
        for entry in tree.manifests.get(record.origin_url, ()):
            entry_id = entry.get("id")
            if isinstance(entry_id, str) and entry_id not in listed:
                missing.add(entry_id)
    if missing:
        raise ValidationError(
            "manifest does not list extensions used in referenced documents: "
            f"{sorted(missing)}"
        )


RECOMMENDED_VALIDATORS = (
    well_under_plate,
    plate_children_are_wells,
    trait_applies_to,
    scale_matches_axes,
    labels_source_resolves,
    manifest_lists_downstream,
)
"""The checks for the revision's recommended-tier traits."""
