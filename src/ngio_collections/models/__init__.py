"""Pure value models reused across the package: ids, paths, references, traits.

No nodes and no IO. The node *spine* is the `graph` layer (`NodeRecord` /
`NodeTree`); this package holds the OME value objects (snake_case on the wire)
that nodes carry and that validation reads: path objects, typed references,
UUID helpers, the extension manifest, the multiscale fields, the coordinate
transformations and the trait models.

Two tiers. The core value types (`DocPath`, `ReferenceObj`, the manifest
entries, the id helpers, `NodeStateError`, `BUILTIN_TRAIT_TYPES`) are stdlib
dataclasses and functions, imported eagerly. The typed value models (`BaseObj`
and everything built on it: traits, `Scale`, `CoordinateSystem`, the
transformations, `MultiscaleFields`) need pydantic, the optional `validate`
extra, and are resolved lazily on first attribute access; without pydantic that
access raises an `ImportError` naming the extra.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ngio_collections._optional import require_pydantic
from ngio_collections.models._errors import NodeStateError
from ngio_collections.models._ids import UUID_PATTERN, is_uuid, new_id
from ngio_collections.models._manifest import (
    ExtensionManifestEntry,
    ExtensionRegistry,
    SchemaRef,
    is_extension_type,
    manifest_entries,
)
from ngio_collections.models._paths import (
    ALL_FORMATS,
    CORE_FORMATS,
    DocPath,
    JsonPath,
    PathFormat,
    PathObj,
    PathType,
    UnsupportedPathFormatError,
    ZarrPath,
)
from ngio_collections.models._references import ReferenceObj
from ngio_collections.models._vocabulary import BUILTIN_TRAIT_TYPES

if TYPE_CHECKING:
    from ngio_collections.models._config import BaseObj, UuidStr
    from ngio_collections.models._multiscale import (
        Axis,
        CoordinateSystem,
        MultiscaleFields,
        Scale,
    )
    from ngio_collections.models._transformation import (
        AffineTransformation,
        BijectionTransformation,
        ByDimensionItem,
        ByDimensionTransformation,
        CoordinatesTransformation,
        CoordinateTransformation,
        CustomTransformation,
        DisplacementsTransformation,
        IdentityTransformation,
        MapAxisTransformation,
        RotationTransformation,
        ScaleTransformation,
        SequenceTransformation,
        TranslationTransformation,
    )
    from ngio_collections.models.traits import (
        AcquisitionObj,
        AcquisitionTrait,
        BaseTrait,
        ColumnObj,
        LabelObj,
        LabelsTrait,
        PlateTrait,
        RgbaColor,
        RowObj,
        SceneTrait,
        TraitType,
        UnknownTrait,
        WellTrait,
    )

_CONFIG = "ngio_collections.models._config"
_MULTISCALE = "ngio_collections.models._multiscale"
_TRANSFORMATION = "ngio_collections.models._transformation"
_TRAITS = "ngio_collections.models.traits"

_LAZY: dict[str, str] = {
    "BaseObj": _CONFIG,
    "UuidStr": _CONFIG,
    "Axis": _MULTISCALE,
    "CoordinateSystem": _MULTISCALE,
    "MultiscaleFields": _MULTISCALE,
    "Scale": _MULTISCALE,
    "AffineTransformation": _TRANSFORMATION,
    "BijectionTransformation": _TRANSFORMATION,
    "ByDimensionItem": _TRANSFORMATION,
    "ByDimensionTransformation": _TRANSFORMATION,
    "CoordinatesTransformation": _TRANSFORMATION,
    "CoordinateTransformation": _TRANSFORMATION,
    "CustomTransformation": _TRANSFORMATION,
    "DisplacementsTransformation": _TRANSFORMATION,
    "IdentityTransformation": _TRANSFORMATION,
    "MapAxisTransformation": _TRANSFORMATION,
    "RotationTransformation": _TRANSFORMATION,
    "ScaleTransformation": _TRANSFORMATION,
    "SequenceTransformation": _TRANSFORMATION,
    "TranslationTransformation": _TRANSFORMATION,
    "AcquisitionObj": _TRAITS,
    "AcquisitionTrait": _TRAITS,
    "BaseTrait": _TRAITS,
    "ColumnObj": _TRAITS,
    "LabelObj": _TRAITS,
    "LabelsTrait": _TRAITS,
    "PlateTrait": _TRAITS,
    "RgbaColor": _TRAITS,
    "RowObj": _TRAITS,
    "SceneTrait": _TRAITS,
    "TraitType": _TRAITS,
    "UnknownTrait": _TRAITS,
    "WellTrait": _TRAITS,
}
"""Typed value models (pydantic) → the submodule that defines them."""

PYDANTIC_NAMES: frozenset[str] = frozenset(_LAZY)
"""The public model names that need the `validate` extra."""


def __getattr__(name: str):  # noqa: D103  (PEP 562 lazy loader)
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    require_pydantic(f"ngio_collections.{name}")
    import importlib

    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value  # cache: later lookups skip this hook
    return value


def __dir__() -> list[str]:  # noqa: D103
    return sorted(set(globals()) | PYDANTIC_NAMES)


__all__ = [
    "ALL_FORMATS",
    "BUILTIN_TRAIT_TYPES",
    "CORE_FORMATS",
    "UUID_PATTERN",
    "AcquisitionObj",
    "AcquisitionTrait",
    "AffineTransformation",
    "Axis",
    "BaseObj",
    "BaseTrait",
    "BijectionTransformation",
    "ByDimensionItem",
    "ByDimensionTransformation",
    "ColumnObj",
    "CoordinateSystem",
    "CoordinateTransformation",
    "CoordinatesTransformation",
    "CustomTransformation",
    "DisplacementsTransformation",
    "DocPath",
    "ExtensionManifestEntry",
    "ExtensionRegistry",
    "IdentityTransformation",
    "JsonPath",
    "LabelObj",
    "LabelsTrait",
    "MapAxisTransformation",
    "MultiscaleFields",
    "NodeStateError",
    "PathFormat",
    "PathObj",
    "PathType",
    "PlateTrait",
    "ReferenceObj",
    "RgbaColor",
    "RotationTransformation",
    "RowObj",
    "Scale",
    "ScaleTransformation",
    "SceneTrait",
    "SchemaRef",
    "SequenceTransformation",
    "TraitType",
    "TranslationTransformation",
    "UnknownTrait",
    "UnsupportedPathFormatError",
    "UuidStr",
    "WellTrait",
    "ZarrPath",
    "is_extension_type",
    "is_uuid",
    "manifest_entries",
    "new_id",
]
