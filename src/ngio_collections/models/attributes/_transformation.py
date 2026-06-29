"""Coordinate transformation models (RFC-5 taxonomy, RFC-8 references).

RFC-8 defers transform details to RFC-5 (status R4, still moving), so the layer
stays forward-compatible: unknown fields round-trip via `BaseObj`'s
`extra="allow"`, and unknown / custom-prefixed `type` values fall back to
`CustomTransformation` instead of raising.

`CoordinateTransformation` is an *open* discriminated union (tagged on `type`).
It is a typing alias, not a class — construct a concrete type
(`ScaleTransformation(...)`, ...) directly; validation (e.g. `model_validate`)
dispatches to the right member.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Discriminator, Tag

from ngio_collections.models._config import BaseObj
from ngio_collections.models._references import ReferenceObj


class _TransformationBase(BaseObj):
    """Fields shared by every transformation.

    `input` / `output` are optional because transforms wrapped inside
    `sequence` / `bijection` / `byDimension` omit them. They carry the RFC-8
    reference shape (`id` + optional `path`), not RFC-5's bare name string.
    """

    name: str | None = None
    input: ReferenceObj | None = None
    output: ReferenceObj | None = None


class IdentityTransformation(_TransformationBase):
    type: Literal["identity"] = "identity"


class MapAxisTransformation(_TransformationBase):
    type: Literal["mapAxis"] = "mapAxis"

    map_axis: list[int]


class TranslationTransformation(_TransformationBase):
    type: Literal["translation"] = "translation"

    translation: list[float] | None = None
    path: str | None = None


class ScaleTransformation(_TransformationBase):
    type: Literal["scale"] = "scale"

    scale: list[float] | None = None
    path: str | None = None


class AffineTransformation(_TransformationBase):
    type: Literal["affine"] = "affine"

    affine: list[list[float]] | None = None
    path: str | None = None


class RotationTransformation(_TransformationBase):
    type: Literal["rotation"] = "rotation"

    rotation: list[list[float]] | None = None
    path: str | None = None


class SequenceTransformation(_TransformationBase):
    type: Literal["sequence"] = "sequence"

    transformations: list[CoordinateTransformation]


class DisplacementsTransformation(_TransformationBase):
    type: Literal["displacements"] = "displacements"

    path: str


class CoordinatesTransformation(_TransformationBase):
    type: Literal["coordinates"] = "coordinates"

    path: str


class BijectionTransformation(_TransformationBase):
    type: Literal["bijection"] = "bijection"

    forward: CoordinateTransformation
    inverse: CoordinateTransformation


class ByDimensionItem(BaseObj):
    """One lower-dimensional transform within a `byDimension` composition."""

    input_axes: list[str]
    output_axes: list[str]
    transformation: CoordinateTransformation


class ByDimensionTransformation(_TransformationBase):
    type: Literal["byDimension"] = "byDimension"

    transformations: list[ByDimensionItem]


class CustomTransformation(_TransformationBase):
    """Fallback for unknown / custom-prefixed transform types.

    Keeps its `type` and any extra fields (via `extra="allow"`) so unrecognised
    transforms round-trip untouched rather than failing validation.
    """

    type: str


_KNOWN_TRANSFORM_TYPES = frozenset(
    {
        "identity",
        "mapAxis",
        "translation",
        "scale",
        "affine",
        "rotation",
        "sequence",
        "displacements",
        "coordinates",
        "bijection",
        "byDimension",
    }
)


def _transform_tag(value: Any) -> str:
    """Route a transform to its union member, defaulting to `custom`."""
    if isinstance(value, dict):
        type_ = value.get("type")
    else:
        type_ = getattr(value, "type", None)
    return type_ if type_ in _KNOWN_TRANSFORM_TYPES else "custom"


CoordinateTransformation = Annotated[
    Annotated[IdentityTransformation, Tag("identity")]
    | Annotated[MapAxisTransformation, Tag("mapAxis")]
    | Annotated[TranslationTransformation, Tag("translation")]
    | Annotated[ScaleTransformation, Tag("scale")]
    | Annotated[AffineTransformation, Tag("affine")]
    | Annotated[RotationTransformation, Tag("rotation")]
    | Annotated[SequenceTransformation, Tag("sequence")]
    | Annotated[DisplacementsTransformation, Tag("displacements")]
    | Annotated[CoordinatesTransformation, Tag("coordinates")]
    | Annotated[BijectionTransformation, Tag("bijection")]
    | Annotated[ByDimensionTransformation, Tag("byDimension")]
    | Annotated[CustomTransformation, Tag("custom")],
    Discriminator(_transform_tag),
]
"""Open, `type`-tagged union of all transformations (unknown -> custom)."""


# Resolve the `CoordinateTransformation` forward refs in recursive members.
SequenceTransformation.model_rebuild()
BijectionTransformation.model_rebuild()
ByDimensionItem.model_rebuild()
