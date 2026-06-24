"""Coordinate system, axis, and scene models.

Axes follow RFC-5 (only `name` is required; `type` / `unit` stay loose strings
since the spec only SHOULDs their vocabularies). Transform details live in
`_transformation`. `BaseObj`'s `extra="allow"` round-trips unknown fields while
RFC-5 (status R4) keeps moving.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from ngio_collections.models._base import (
    BaseAttribute,
    BaseListAttribute,
    BaseObj,
    IdStr,
)
from ngio_collections.models.attributes._transformation import (
    CoordinateTransformation,
)


class Axis(BaseObj):
    name: str = Field(min_length=1)
    type: str | None = None
    unit: str | None = None
    discrete: bool | None = None
    long_name: str | None = None


class CoordinateSystem(BaseObj):
    id: IdStr
    name: str | None = None
    axes: list[Axis]


class SceneAttribute(BaseAttribute):
    key: ClassVar[str] = "scene"

    coordinate_systems: list[CoordinateSystem] | None = None
    coordinate_transformations: list[CoordinateTransformation]


class CoordinateSystemsAttribute(BaseListAttribute[CoordinateSystem]):
    key: ClassVar[str] = "coordinateSystems"


class CoordinateTransformationsAttribute(
    BaseListAttribute[CoordinateTransformation]
):
    key: ClassVar[str] = "coordinateTransformations"
