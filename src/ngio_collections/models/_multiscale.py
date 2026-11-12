"""Multiscale node fields: coordinate systems, transformations and arrays.

The layout follows RFC-8 revision 2 ("`Multiscale` node" and "`Array` object").
A `multiscale` is a leaf node that carries three fields directly on the node,
not in a trait:

- `coordinateSystems`: declarations of type `coordinate_system` (an id plus
  RFC-5 axes).
- `coordinateTransformations`: the transformations from the multiscale's array
  space (that of its highest-resolution array) into those systems. Array
  objects have no id, so `input` references the multiscale itself,
  `{type: "multiscale", ref: <the node's id>}`; `output` is a
  `{type: "coordinate_system", ref}` reference to one of the node's systems,
  the same one for every transformation.
- `data`: one `array` object per resolution level, finest first. Array objects
  are not nodes and are not declarations: they carry no `id` and cannot be
  referenced. An array is located by its `path` (relative to the multiscale
  document, or an absolute / http locator; see `models._paths`). Every array
  but the first declares how it was derived from the first through
  `downsamplingTransformations`: a `scale`, optionally followed by a
  `translation`.

`MultiscaleFields` is the typed view over a multiscale record's `fields`; its
attributes are `coordinate_systems`, `coordinate_transformations` and `arrays`.
Axes follow RFC-5 (only `name` is required; `type` / `unit` stay loose strings
since the spec only SHOULDs their vocabularies).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Discriminator, Field, Tag, model_validator

from ngio_collections.models._config import BaseObj, IdStr, wire
from ngio_collections.models._multiscale_keys import (
    ARRAY_TYPE,
    COORDINATE_SYSTEMS_KEY,
    COORDINATE_TRANSFORMATIONS_KEY,
    DATA_KEY,
    DOWNSAMPLING_KEY,
)
from ngio_collections.models._paths import DocPath
from ngio_collections.models._transformation import CoordinateTransformation


class Axis(BaseObj):
    """One axis of a coordinate system (RFC-5)."""

    name: str = Field(min_length=1)
    type: str | None = None
    unit: str | None = None
    discrete: bool | None = None
    long_name: str | None = None


class CoordinateSystem(BaseObj):
    """A `coordinate_system` declaration: an id plus its axes."""

    type: Literal["coordinate_system"] = "coordinate_system"
    id: IdStr
    name: str | None = None
    axes: list[Axis]


class ScaleDownsampling(BaseObj):
    """A per-axis downsampling factor relative to the full-resolution array."""

    type: Literal["scale"] = "scale"
    scale: list[float]


class TranslationDownsampling(BaseObj):
    """A per-axis offset (in full-resolution array units) of a downsampled array."""

    type: Literal["translation"] = "translation"
    translation: list[float]


def _downsampling_tag(value: Any) -> str | None:
    """Route a downsampling transformation to its union member by `type`."""
    if isinstance(value, dict):
        return value.get("type")
    return getattr(value, "type", None)


Downsampling = Annotated[
    Annotated[ScaleDownsampling, Tag("scale")]
    | Annotated[TranslationDownsampling, Tag("translation")],
    Discriminator(_downsampling_tag),
]
"""One downsampling transformation, tagged on `type` (`scale` or `translation`)."""


class MultiscaleArray(BaseObj):
    """An `array` object: one resolution level of a multiscale.

    `path` locates the level's array and `name` is optional. An array has no
    `id`: it is not a declaration and cannot be referenced.
    `downsamplingTransformations` is absent on the highest-resolution array and
    otherwise one `scale`, optionally followed by one `translation`; the
    attribute keeps the wire spelling.
    """

    type: Literal["array"] = ARRAY_TYPE
    name: str | None = None
    path: DocPath
    downsamplingTransformations: list[Downsampling] | None = Field(  # noqa: N815
        default=None, min_length=1, max_length=2
    )

    @model_validator(mode="after")
    def _scale_then_optional_translation(self) -> MultiscaleArray:
        """Allow `[scale]` or `[scale, translation]` only."""
        if self.downsamplingTransformations is None:
            return self
        kinds = [t.type for t in self.downsamplingTransformations]
        if kinds not in (["scale"], ["scale", "translation"]):
            raise ValueError(
                f"{DOWNSAMPLING_KEY} must be one `scale`, optionally followed by "
                f"one `translation`; got {kinds}"
            )
        return self

    @property
    def scale(self) -> list[float] | None:
        """The downsampling factors, or `None` when the array declares none."""
        return next(
            (
                t.scale
                for t in self.downsamplingTransformations or ()
                if isinstance(t, ScaleDownsampling)
            ),
            None,
        )

    @property
    def translation(self) -> list[float] | None:
        """The offset of the `translation` entry, or `None` when there is none."""
        return next(
            (
                t.translation
                for t in self.downsamplingTransformations or ()
                if isinstance(t, TranslationDownsampling)
            ),
            None,
        )


class MultiscaleFields(BaseObj):
    """The typed view over a `multiscale` record's node fields."""

    coordinate_systems: list[CoordinateSystem] = wire(COORDINATE_SYSTEMS_KEY)
    coordinate_transformations: list[CoordinateTransformation] = wire(
        COORDINATE_TRANSFORMATIONS_KEY
    )
    arrays: list[MultiscaleArray] = wire(DATA_KEY)

    @model_validator(mode="after")
    def _lower_levels_declare_downsampling(self) -> MultiscaleFields:
        """Every array but the first must carry `downsamplingTransformations`."""
        for index, array in enumerate(self.arrays[1:], start=1):
            if array.downsamplingTransformations is None:
                raise ValueError(
                    f"array {index} has no {DOWNSAMPLING_KEY}; only "
                    "the highest-resolution array (the first) may omit it"
                )
        return self
