"""ngio_collections: functional, immutable, round-trip-safe OME collections.

Frozen node values; resolution and editing return new trees and never mutate the
source. `open` reads one editable document (cross-document children stay
`RefNode` stubs); `open_inlined` resolves references across boundaries into a
read-only `InlinedNode` tree. Writing is single-document (`create` / `save`),
with `save_inlined` to snapshot a resolved tree; each returns a `ReferenceObj`
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
    AnyInlinedNode,
    AnyNode,
    BaseNode,
    CollectionNode,
    IdStr,
    InlinedCollectionNode,
    InlinedMultiscaleNode,
    InlinedNode,
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
    ReferenceObj,
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
    "AnyInlinedNode",
    "AnyNode",
    "BaseNode",
    "CollectionNode",
    "FsspecStore",
    "IdStr",
    "InlinedCollectionNode",
    "InlinedMultiscaleNode",
    "InlinedNode",
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
    "ReferenceObj",
    "Resolver",
    "StoreReadOnlyError",
    "WritableStore",
    "ZarrPath",
    "create",
    "delete",
    "open",
    "open_inlined",
    "save",
    "save_inlined",
]
