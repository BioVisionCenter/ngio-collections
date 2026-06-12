"""ome-zarr-collections: OME-NGFF RFC-8 collection metadata.

Parse, validate, navigate, edit, and write back collection metadata
documents. Async-first. See DESIGN.md for the architecture.
"""

from ome_zarr_collections.api import (
    open_collection,
    open_multiscale,
    write_collection,
    write_multiscale,
)
from ome_zarr_collections.document import (
    MetadataDocument,
    MetadataDocumentForm,
    NotOmeDocumentError,
    parse_metadata_document,
)
from ome_zarr_collections.models import (
    AcquisitionAttribute,
    BaseAttribute,
    BaseListAttribute,
    BaseNode,
    BaseObj,
    CollectionNode,
    CollectionRef,
    CoordinateSystem,
    CoordinateSystemsAttribute,
    CoordinateTransformation,
    CoordinateTransformationsAttribute,
    JsonPath,
    LabelsAttribute,
    MultiscaleNode,
    MultiscaleRef,
    PathObj,
    PlateAttribute,
    ReferenceObj,
    SceneAttribute,
    SinglescaleNode,
    WellAttribute,
    ZarrPath,
    merged_attributes,
)
from ome_zarr_collections.registry import DEFAULT_REGISTRY, NodeRegistry
from ome_zarr_collections.resolver import Resolver
from ome_zarr_collections.store import (
    FsspecStore,
    LocalStore,
    ReadableStore,
    StoreReadOnlyError,
    WritableStore,
)

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_REGISTRY",
    "AcquisitionAttribute",
    "BaseAttribute",
    "BaseListAttribute",
    "BaseNode",
    "BaseObj",
    "CollectionNode",
    "CollectionRef",
    "CoordinateSystem",
    "CoordinateSystemsAttribute",
    "CoordinateTransformation",
    "CoordinateTransformationsAttribute",
    "MetadataDocument",
    "MetadataDocumentForm",
    "FsspecStore",
    "JsonPath",
    "LabelsAttribute",
    "LocalStore",
    "MultiscaleNode",
    "MultiscaleRef",
    "NodeRegistry",
    "NotOmeDocumentError",
    "PathObj",
    "PlateAttribute",
    "ReadableStore",
    "ReferenceObj",
    "Resolver",
    "SceneAttribute",
    "SinglescaleNode",
    "StoreReadOnlyError",
    "WellAttribute",
    "WritableStore",
    "ZarrPath",
    "merged_attributes",
    "open_collection",
    "open_multiscale",
    "parse_metadata_document",
    "write_collection",
    "write_multiscale",
]
