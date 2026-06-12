"""Store layer: protocols and backends. The only IO surface of the package."""

from ome_zarr_collections.store.fsspec import FsspecStore
from ome_zarr_collections.store.local import LocalStore
from ome_zarr_collections.store.protocols import (
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
