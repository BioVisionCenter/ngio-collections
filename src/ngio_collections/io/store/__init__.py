"""Store layer: protocols and backends. The only IO surface of the package."""

from ngio_collections.io.store._fsspec import FsspecStore
from ngio_collections.io.store._local import LocalStore
from ngio_collections.io.store._memory import MemoryStore
from ngio_collections.io.store._protocols import (
    ReadableStore,
    StoreReadOnlyError,
    WritableStore,
)
from ngio_collections.io.store._postgres._store import PostgresStore

__all__ = [
    "FsspecStore",
    "LocalStore",
    "MemoryStore",
    "PostgresStore",
    "ReadableStore",
    "StoreReadOnlyError",
    "WritableStore",
]
