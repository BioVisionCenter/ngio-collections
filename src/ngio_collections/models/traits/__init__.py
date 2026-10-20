"""Typed trait models and the trait base classes.

The base infra (`BaseTrait`, `UnknownTrait`, `TraitType`) lives in `_base`;
`_scene` holds the one trait RFC-8 revision 1 defines itself, and
`_provisional` the recommended HCS / labels traits that are deferred to
sub-RFCs. Re-exported here so consumers have a single trait import surface.
"""

from ngio_collections.models.traits._base import BaseTrait, TraitType, UnknownTrait
from ngio_collections.models.traits._provisional import (
    AcquisitionObj,
    AcquisitionTrait,
    ColumnObj,
    LabelObj,
    LabelsTrait,
    PlateTrait,
    RgbaColor,
    RowObj,
    WellTrait,
)
from ngio_collections.models.traits._scene import SceneTrait

BUILTIN_TRAIT_TYPES: frozenset[str] = frozenset(
    {"scene", "plate", "well", "acquisition", "labels", "bioformats2raw"}
)
"""Keyword trait types the revision names (core or recommended tier)."""

__all__ = [
    "BUILTIN_TRAIT_TYPES",
    "AcquisitionObj",
    "AcquisitionTrait",
    "BaseTrait",
    "ColumnObj",
    "LabelObj",
    "LabelsTrait",
    "PlateTrait",
    "RgbaColor",
    "RowObj",
    "SceneTrait",
    "TraitType",
    "UnknownTrait",
    "WellTrait",
]
