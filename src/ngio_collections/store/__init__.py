"""Store layer: protocols and backends. The only IO surface of the package."""

from ngio_collections.store.fsspec import FsspecStore
from ngio_collections.store.local import LocalStore
from ngio_collections.store.protocols import (
    ReadableStore,
    StoreReadOnlyError,
    WritableStore,
)

__all__ = [
    "FsspecStore",
    "LocalStore",
    "ReadableStore",
    "StoreReadOnlyError",
    "WritableStore",
]
