"""The v5 public API: the `Node` handle, the open/save/inline verbs, and models.

This module is the composition root: it explicitly wires the typed `Node`
subclasses and the built-in validators (rather than relying on import-side-effect
self-registration). The synchronous verbs are the common case; the async core
lives in `ngio_collections.api._api`. The value models (attributes, paths,
references) and store backends are re-exported here so the whole surface is one
import.
"""

from __future__ import annotations

from ngio_collections import models as _models
from ngio_collections.api._node import (
    CollectionNode,
    MultiscaleNode,
    Node,
    NodeTypeRegistry,
    SinglescaleNode,
    new_node,
    register_node_type,
    register_node_types,
    wrap_node,
)
from ngio_collections.graph import Reference
from ngio_collections.api._sync import (
    create,
    delete,
    externalize,
    open,
    open_inlined,
    open_inlined_ref,
    open_ref,
    save,
    save_inlined,
)
from ngio_collections.io import fingerprint
from ngio_collections.io.store import (
    FsspecStore,
    LocalStore,
    MemoryStore,
    AnyReadableStore,
    AsyncReadableStore,
    StoreDuplicateValueError,
    StoreReadOnlyError,
    AsyncWritableStore,
    SyncReadableStore,
    SyncWritableStore,
)
from ngio_collections.models import *  # noqa: F403  (value models: attributes, paths, refs)
from ngio_collections.validate import (
    ValidationError,
    ValidatorType,
    scale_matches_axes,
    validate,
    well_under_plate,
)

# Composition root: wire the typed handles explicitly. Validators are passed
# explicitly per call (no global registry) as a sequence of plain callables.
register_node_types()

_API = [
    "AnyReadableStore",
    "AsyncReadableStore",
    "AsyncWritableStore",
    "CollectionNode",
    "FsspecStore",
    "LocalStore",
    "MemoryStore",
    "MultiscaleNode",
    "Node",
    "NodeTypeRegistry",
    "Reference",
    "SinglescaleNode",
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
    "new_node",
    "open",
    "open_inlined",
    "open_inlined_ref",
    "open_ref",
    "register_node_type",
    "register_node_types",
    "save",
    "save_inlined",
    "scale_matches_axes",
    "validate",
    "well_under_plate",
    "wrap_node",
]

__all__ = sorted(_API + list(_models.__all__))
