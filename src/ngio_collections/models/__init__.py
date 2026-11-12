"""Pure value models reused across the package: ids, paths, references, traits.

No nodes and no IO. The node *spine* is the `graph` layer (`NodeRecord` /
`NodeTree`); this package holds the OME value objects (wire keys as the revision spells them)
that nodes carry and that validation reads: path objects, typed references,
id helpers, the extension manifest, the multiscale fields, the coordinate
transformations and the trait models.

Two tiers. The core value types (`DocPath`, `ReferenceObj`, the manifest
entries, the id helpers, `NodeStateError`, `BUILTIN_TRAIT_TYPES`) are stdlib
dataclasses and functions, imported eagerly. The typed value models (`BaseObj`
and everything built on it: traits, `MultiscaleArray`, `CoordinateSystem`, the
transformations, `MultiscaleFields`) need pydantic, the optional `validate`
extra, and are resolved lazily on first attribute access; without pydantic that
access raises an `ImportError` naming the extra.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ngio_collections._optional import require_pydantic
from ngio_collections.models._errors import NodeStateError
from ngio_collections.models._ids import ID_PATTERN, is_id, new_id
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
from ngio_collections.models._multiscale_keys import ARRAY_TYPE, DOWNSAMPLING_KEY
from ngio_collections.models._vocabulary import BUILTIN_TRAIT_TYPES

if TYPE_CHECKING:
    from ngio_collections.models._config import BaseObj, IdStr
    from ngio_collections.models._multiscale import (
        Axis,
        CoordinateSystem,
        Downsampling,
        MultiscaleArray,
        MultiscaleFields,
        ScaleDownsampling,
        TranslationDownsampling,
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
    "IdStr": _CONFIG,
    "Axis": _MULTISCALE,
    "CoordinateSystem": _MULTISCALE,
    "Downsampling": _MULTISCALE,
    "MultiscaleArray": _MULTISCALE,
    "MultiscaleFields": _MULTISCALE,
    "ScaleDownsampling": _MULTISCALE,
    "TranslationDownsampling": _MULTISCALE,
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
    "DOWNSAMPLING_KEY",
    "ID_PATTERN",
    "ARRAY_TYPE",
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
    "Downsampling",
    "ExtensionManifestEntry",
    "ExtensionRegistry",
    "IdStr",
    "IdentityTransformation",
    "JsonPath",
    "LabelObj",
    "LabelsTrait",
    "MapAxisTransformation",
    "MultiscaleArray",
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
    "ScaleDownsampling",
    "ScaleTransformation",
    "SceneTrait",
    "SchemaRef",
    "SequenceTransformation",
    "TraitType",
    "TranslationDownsampling",
    "TranslationTransformation",
    "UnknownTrait",
    "UnsupportedPathFormatError",
    "WellTrait",
    "ZarrPath",
    "is_extension_type",
    "is_id",
    "manifest_entries",
    "new_id",
]
