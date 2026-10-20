"""Multiscale node fields: axes, coordinate systems and scales (RFC-8 rev. 1 §8).

A `multiscale` node carries two fields directly on the node, not in a trait:
`coordinate_systems` (declarations of type `coordinate_system`) and `scales`
(declarations of type `scale`, each locating one resolution level's array and
carrying the transformations that map it into a coordinate system). This is the
revision's replacement for both the 0.6 `datasets` array and RFC-8's former
`singlescale` child nodes. `MultiscaleFields` is the typed view over a
multiscale record's `fields`.

Axes follow RFC-5 (only `name` is required; `type` / `unit` stay loose strings
since the spec only SHOULDs their vocabularies).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ngio_collections.models._config import BaseObj, UuidStr
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
    """A `coordinate_system` declaration: a UUID plus its axes."""

    type: Literal["coordinate_system"] = "coordinate_system"
    id: UuidStr
    name: str | None = None
    axes: list[Axis]


class Scale(BaseObj):
    """A `scale` declaration: one resolution level and its transformations.

    `path` locates the level's array (relative to the multiscale document, or an
    absolute / http locator; see `models._paths`). `coordinate_transformations`
    map `{type: "scale", ref: <this id>}` into one of the multiscale's
    coordinate systems.
    """

    type: Literal["scale"] = "scale"
    id: UuidStr
    path: DocPath
    coordinate_transformations: list[CoordinateTransformation] = Field(
        default_factory=list
    )


class MultiscaleFields(BaseObj):
    """The typed view over a `multiscale` record's node fields."""

    coordinate_systems: list[CoordinateSystem]
    scales: list[Scale]
