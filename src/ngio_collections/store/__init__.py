"""Store layer: protocols and backends. The only IO surface of the package."""

from ngio_collections.store._fsspec import FsspecStore
from ngio_collections.store._local import LocalStore
from ngio_collections.store._protocols import (
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
