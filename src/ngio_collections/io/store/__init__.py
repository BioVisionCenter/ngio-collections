"""Store layer: protocols and backends. The only IO surface of the package."""

from ngio_collections.io.store._fsspec import FsspecStore
from ngio_collections.io.store._http import HttpStore
from ngio_collections.io.store._local import LocalStore
from ngio_collections.io.store._memory import MemoryStore
from ngio_collections.io.store._protocols import (
    AnyReadableStore,
    AsyncReadableStore,
    AsyncWritableStore,
    StoreDuplicateValueError,
    StoreReadOnlyError,
    SyncReadableStore,
    SyncWritableStore,
)
from ngio_collections.io.store._routed import RoutedStore, default_store

__all__ = [
    "AnyReadableStore",
    "AsyncReadableStore",
    "AsyncWritableStore",
    "FsspecStore",
    "HttpStore",
    "LocalStore",
    "MemoryStore",
    "RoutedStore",
    "StoreDuplicateValueError",
    "StoreReadOnlyError",
    "SyncReadableStore",
    "SyncWritableStore",
    "default_store",
]
