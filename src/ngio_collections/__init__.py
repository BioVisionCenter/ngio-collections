"""ngio_collections: functional, immutable, round-trip-safe OME collections.

Frozen node values; resolution and editing return new trees and never mutate the
source; provenance lives off the wire in PrivateAttr. The §5 merge rule has a
single home (``merge`` / ``split``, internal to ``models._base``).

The public surface is deliberately small: the :class:`Resolver`, the store
backends and protocols, and the node/path model types needed to build and
annotate trees. The merge engine, node constructors, provenance dataclasses, and
the document layer are internal (reachable via the private modules if needed).
"""

from ngio_collections._resolver import Resolver
from ngio_collections.models import (
    AnyNode,
    CollectionNode,
    JsonPath,
    MultiscaleNode,
    Node,
    NodeState,
    NodeStateError,
    PathObj,
    RefCollectionNode,
    RefMultiscaleNode,
    RefNode,
    RefSinglescaleNode,
    ZarrPath,
)
from ngio_collections.store import (
    FsspecStore,
    LocalStore,
    ReadableStore,
    StoreReadOnlyError,
    WritableStore,
)

__all__ = [
    "AnyNode",
    "CollectionNode",
    "FsspecStore",
    "JsonPath",
    "LocalStore",
    "MultiscaleNode",
    "Node",
    "NodeState",
    "NodeStateError",
    "PathObj",
    "ReadableStore",
    "RefCollectionNode",
    "RefMultiscaleNode",
    "RefNode",
    "RefSinglescaleNode",
    "Resolver",
    "StoreReadOnlyError",
    "WritableStore",
    "ZarrPath",
]
