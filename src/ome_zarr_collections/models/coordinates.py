"""Coordinate system and transformation models.

Deliberately loose while RFC-5 is moving: axes and transform details stay
untyped, preserved via ``extra="allow"`` (DESIGN.md §7).
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import JsonValue

from ome_zarr_collections.models.base import (
    BaseAttribute,
    BaseListAttribute,
    BaseObj,
    IdStr,
    ReferenceObj,
)


class CoordinateSystem(BaseObj):
    id: IdStr
    name: str | None = None
    axes: list[JsonValue]


class CoordinateTransformation(BaseObj):
    # Extra fields (scale, translation, ...) are preserved via extra="allow".
    type: str
    input: ReferenceObj
    output: ReferenceObj


class SceneAttribute(BaseAttribute):
    key: ClassVar[str] = "scene"

    coordinate_systems: list[CoordinateSystem] | None = None
    coordinate_transformations: list[CoordinateTransformation]


class CoordinateSystemsAttribute(BaseListAttribute[CoordinateSystem]):
    key: ClassVar[str] = "coordinateSystems"


class CoordinateTransformationsAttribute(BaseListAttribute[CoordinateTransformation]):
    key: ClassVar[str] = "coordinateTransformations"
