"""Pure value models reused across the package: ids, paths, references, traits.

No nodes and no IO. The node *spine* is the `graph` layer (`NodeRecord` /
`NodeTree`); this package holds the OME value objects (snake_case on the wire)
that nodes carry and that validation reads: path objects, typed references,
UUID helpers, the extension manifest, the multiscale fields, the coordinate
transformations and the trait models.
"""

from ngio_collections.models._config import BaseObj, NodeStateError
from ngio_collections.models._ids import UUID_PATTERN, UuidStr, is_uuid, new_id
from ngio_collections.models._manifest import (
    ExtensionManifestEntry,
    ExtensionRegistry,
    SchemaRef,
    is_extension_type,
    manifest_entries,
)
from ngio_collections.models._multiscale import (
    Axis,
    CoordinateSystem,
    MultiscaleFields,
    Scale,
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
    BUILTIN_TRAIT_TYPES,
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
