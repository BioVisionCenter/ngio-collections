"""ngio_collections: functional, immutable, round-trip-safe OME collections.

Frozen node values; resolution and editing return new trees and never mutate the
source. `open` reads one editable document (cross-document children stay
`RefNode` stubs); `open_inlined` resolves references across boundaries into a
read-only `InlinedNode` tree. Both accept either a document URL or a
`ReferenceObj` (then returning the node it locates). Writing is single-document
(`create` / `save`),
with `save_inlined` to snapshot a resolved tree; each returns a `RefNode`
so documents compose bottom-up via `add_ref`.

The public surface is deliberately small: the :class:`Resolver`, the store
backends and protocols, and the node/path/reference model types needed to build,
annotate, and compose trees. Node constructors and the document layer are
internal (reachable via the private modules if needed).
"""

from ngio_collections._resolver import Resolver
from ngio_collections._sync import (
    create,
    delete,
    open,
    open_inlined,
    save,
    save_inlined,
)
from ngio_collections.models import (
    DEFAULT_REGISTRY,
    AnyInlinedNode,
    AnyNode,
    BaseNode,
    CollectionNode,
    CollectionType,
    IdStr,
    InlinedCollectionNode,
    InlinedMultiscaleNode,
    InlinedNode,
    JsonPath,
    MultiscaleNode,
    MultiscaleType,
    Node,
    NodeObj,
    NodeRegistry,
    NodeState,
    NodeStateError,
    NodeTypes,
    PathObj,
    RefCollectionNode,
    RefMultiscaleNode,
    RefNode,
    RefSinglescaleNode,
    ReferenceObj,
    SinglescaleType,
    ZarrPath,
    register_family,
)
from ngio_collections.store import (
    FsspecStore,
    LocalStore,
    ReadableStore,
    StoreReadOnlyError,
    WritableStore,
)

__all__ = [
    "DEFAULT_REGISTRY",
    "AnyInlinedNode",
    "AnyNode",
    "BaseNode",
    "CollectionNode",
    "CollectionType",
    "FsspecStore",
    "IdStr",
    "InlinedCollectionNode",
    "InlinedMultiscaleNode",
    "InlinedNode",
    "JsonPath",
    "LocalStore",
    "MultiscaleNode",
    "MultiscaleType",
    "Node",
    "NodeObj",
    "NodeRegistry",
    "NodeState",
    "NodeStateError",
    "NodeTypes",
    "PathObj",
    "ReadableStore",
    "RefCollectionNode",
    "RefMultiscaleNode",
    "RefNode",
    "RefSinglescaleNode",
    "ReferenceObj",
    "SinglescaleType",
    "Resolver",
    "StoreReadOnlyError",
    "WritableStore",
    "ZarrPath",
    "create",
    "delete",
    "open",
    "open_inlined",
    "register_family",
    "save",
    "save_inlined",
]
