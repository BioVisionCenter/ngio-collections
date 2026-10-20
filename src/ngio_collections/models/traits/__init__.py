"""Typed trait models and the trait base classes.

The base infra (`BaseTrait`, `UnknownTrait`, `TraitType`) lives in `_base`;
`_scene` holds the one trait RFC-8 revision 1 defines itself, and
`_provisional` the recommended HCS / labels traits that are deferred to
sub-RFCs. Re-exported here so consumers have a single trait import surface.
"""

from ngio_collections.models._vocabulary import BUILTIN_TRAIT_TYPES
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
