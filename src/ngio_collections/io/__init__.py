"""IO / resolution layer: stores, documents, and the resolver.

The only IO surface of the package. `Resolver` orchestrates reading, inlining,
and persisting trees over a URL-addressed `store`; the sync free functions mirror
its surface for scripts and notebooks. Imports from `models` and `treeops`.
"""

from ngio_collections.io._document import (
    JsonMetadataDocument,
    MetadataDocument,
    ZarrMetadataDocument,
)
from ngio_collections.io._resolver import Resolver
from ngio_collections.io._sync import (
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

__all__ = [
    "FsspecStore",
    "JsonMetadataDocument",
    "LocalStore",
    "MetadataDocument",
    "ReadableStore",
    "Resolver",
    "StoreReadOnlyError",
    "WritableStore",
    "ZarrMetadataDocument",
    "create",
    "delete",
    "open",
    "open_inlined",
    "save",
    "save_inlined",
]
