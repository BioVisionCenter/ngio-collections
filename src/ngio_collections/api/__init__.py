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
    open,
    open_inlined,
    save,
    save_inlined,
)
from ngio_collections.io.store import (
    FsspecStore,
    LocalStore,
    ReadableStore,
    StoreReadOnlyError,
    WritableStore,
)
from ngio_collections.models import *  # noqa: F403  (value models: attributes, paths, refs)
from ngio_collections.validate import (
    DEFAULT_VALIDATORS,
    Issue,
    Scope,
    register_builtins,
    validate,
    validate_tree,
)

# Composition root: wire typed handles and built-in validators explicitly.
register_node_types()
register_builtins(DEFAULT_VALIDATORS)

_API = [
    "CollectionNode",
    "FsspecStore",
    "Issue",
    "LocalStore",
    "MultiscaleNode",
    "Node",
    "NodeTypeRegistry",
    "ReadableStore",
    "Reference",
    "Scope",
    "SinglescaleNode",
    "StoreReadOnlyError",
    "WritableStore",
    "create",
    "delete",
    "new_node",
    "open",
    "open_inlined",
    "register_node_type",
    "register_node_types",
    "save",
    "save_inlined",
    "validate",
    "validate_tree",
    "wrap_node",
]

__all__ = sorted(_API + list(_models.__all__))
