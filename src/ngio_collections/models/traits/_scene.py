"""The `scene` trait: coordinate systems and transformations of a collection."""

from __future__ import annotations

from typing import ClassVar, Literal

from ngio_collections.models._config import wire
from ngio_collections.models._multiscale import CoordinateSystem
from ngio_collections.models._multiscale_keys import (
    COORDINATE_SYSTEMS_KEY,
    COORDINATE_TRANSFORMATIONS_KEY,
)
from ngio_collections.models._transformation import CoordinateTransformation
from ngio_collections.models.traits._base import BaseTrait


class SceneTrait(BaseTrait):
    """Spatial information about the nodes *within* a collection.

    `coordinate_systems` declares the collection's own systems;
    `coordinate_transformations` relate the member images' systems (referenced
    with a `path`) to them. On the wire they are `coordinateSystems` (optional)
    and `coordinateTransformations` (required).
    """

    applies_to: ClassVar[frozenset[str]] = frozenset({"collection"})

    type: Literal["scene"] = "scene"
    coordinate_systems: list[CoordinateSystem] = wire(
        COORDINATE_SYSTEMS_KEY, default_factory=list
    )
    coordinate_transformations: list[CoordinateTransformation] = wire(
        COORDINATE_TRANSFORMATIONS_KEY
    )
