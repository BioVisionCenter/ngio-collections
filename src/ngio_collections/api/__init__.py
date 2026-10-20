"""The public API: the `Node` handle, the open/save/resolve verbs, and models.

This module is the composition root: it explicitly wires the typed `Node`
subclasses (rather than relying on import-side-effect self-registration). The
synchronous verbs are the common case; the async core lives in
`ngio_collections.api._api`. The value models (traits, paths, references, the
multiscale fields) and store backends are re-exported here so the whole surface
is one import.
"""

from __future__ import annotations

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
from ngio_collections.models import *  # noqa: F403  (value models: traits, paths, refs)
from ngio_collections.validate import (
    ALL_VALIDATORS,
    CORE_VALIDATORS,
    RECOMMENDED_VALIDATORS,
    ValidationError,
    ValidatorType,
    paths_are_core,
    validate,
)

# Composition root: wire the typed handles explicitly. Validators are passed
# explicitly per call (no global registry) as a sequence of plain callables.
register_node_types()

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

__all__ = sorted(_API + list(_models.__all__))
