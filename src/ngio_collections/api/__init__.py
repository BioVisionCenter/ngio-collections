"""The public API: the `Node` handle, the open/save/resolve verbs, and models.

This module is the composition root: it explicitly wires the typed `Node`
subclasses (rather than relying on import-side-effect self-registration). The
synchronous verbs are the common case; the async core lives in
`ngio_collections.api._api`. The value models (traits, paths, references, the
multiscale fields) and store backends are re-exported here so the whole surface
is one import. The pydantic value models are forwarded lazily (see
`ngio_collections.models`): importing this module never needs pydantic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ngio_collections import models as _models
from ngio_collections.api._extensions import EXTENSIONS, register_extension
from ngio_collections.api._node import (
    CollectionNode,
    MultiscaleNode,
    Node,
    NodeTypeRegistry,
    new_collection,
    new_multiscale,
    new_node,
    register_node_type,
    register_node_types,
    wrap_node,
)
from ngio_collections.api._sync import (
    create,
    delete,
    externalize,
    open,
    open_ref,
    open_resolved,
    open_resolved_ref,
    resolve_ref,
    save,
)
from ngio_collections.io import fingerprint
from ngio_collections.io.store import (
    AnyReadableStore,
    AsyncReadableStore,
    AsyncWritableStore,
    FsspecStore,
    HttpStore,
    LocalStore,
    MemoryStore,
    RoutedStore,
    StoreDuplicateValueError,
    StoreReadOnlyError,
    SyncReadableStore,
    SyncWritableStore,
)
from ngio_collections.models import (
    ALL_FORMATS,
    BUILTIN_TRAIT_TYPES,
    CORE_FORMATS,
    UUID_PATTERN,
    DocPath,
    ExtensionManifestEntry,
    ExtensionRegistry,
    JsonPath,
    NodeStateError,
    PathFormat,
    PathObj,
    PathType,
    ReferenceObj,
    SchemaRef,
    UnsupportedPathFormatError,
    ZarrPath,
    is_extension_type,
    is_uuid,
    manifest_entries,
    new_id,
)
from ngio_collections.validate import (
    ALL_VALIDATORS,
    CORE_VALIDATORS,
    RECOMMENDED_VALIDATORS,
    ValidationError,
    ValidatorType,
    paths_are_core,
    validate,
)

if TYPE_CHECKING:
    from ngio_collections.models import (  # noqa: F401
        AcquisitionObj,
        AcquisitionTrait,
        AffineTransformation,
        Axis,
        BaseObj,
        BaseTrait,
        BijectionTransformation,
        ByDimensionItem,
        ByDimensionTransformation,
        ColumnObj,
        CoordinateSystem,
        CoordinatesTransformation,
        CoordinateTransformation,
        CustomTransformation,
        DisplacementsTransformation,
        IdentityTransformation,
        LabelObj,
        LabelsTrait,
        MapAxisTransformation,
        MultiscaleFields,
        PlateTrait,
        RgbaColor,
        RotationTransformation,
        RowObj,
        Scale,
        ScaleTransformation,
        SceneTrait,
        SequenceTransformation,
        TraitType,
        TranslationTransformation,
        UnknownTrait,
        UuidStr,
        WellTrait,
    )

# Composition root: wire the typed handles explicitly. Validators are passed
# explicitly per call (no global registry) as a sequence of plain callables.
register_node_types()


def __getattr__(name: str):  # noqa: D103  (PEP 562: forward the pydantic models)
    if name in _models.PYDANTIC_NAMES:
        value = getattr(_models, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


_API = [
    "ALL_VALIDATORS",
    "AnyReadableStore",
    "AsyncReadableStore",
    "AsyncWritableStore",
    "CORE_VALIDATORS",
    "CollectionNode",
    "EXTENSIONS",
    "FsspecStore",
    "HttpStore",
    "LocalStore",
    "MemoryStore",
    "MultiscaleNode",
    "Node",
    "NodeTypeRegistry",
    "RECOMMENDED_VALIDATORS",
    "RoutedStore",
    "StoreDuplicateValueError",
    "StoreReadOnlyError",
    "SyncReadableStore",
    "SyncWritableStore",
    "ValidationError",
    "ValidatorType",
    "create",
    "delete",
    "externalize",
    "fingerprint",
    "new_collection",
    "new_multiscale",
    "new_node",
    "open",
    "open_ref",
    "open_resolved",
    "open_resolved_ref",
    "paths_are_core",
    "register_extension",
    "register_node_type",
    "register_node_types",
    "resolve_ref",
    "save",
    "validate",
    "wrap_node",
]

PYDANTIC_NAMES = _models.PYDANTIC_NAMES
"""Names in `__all__` that need the `validate` extra (resolved lazily)."""

__all__ = sorted(_API + list(_models.__all__))
