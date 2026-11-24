"""IO layer: the URL-addressed store backends and protocols.

The only IO surface of the package. JSON (de)serialization lives in `_json`; the
resolution / read-write orchestration is the `resolve` and `api` layers.
"""

from ngio_collections.io._json import fingerprint
from ngio_collections.io.store import (
    AsyncReadableStore,
    AsyncWritableStore,
    FsspecStore,
    HttpStore,
    LocalStore,
    MemoryStore,
    RoutedStore,
    StoreReadOnlyError,
    default_store,
)

__all__ = [
    "AsyncReadableStore",
    "AsyncWritableStore",
    "FsspecStore",
    "HttpStore",
    "LocalStore",
    "MemoryStore",
    "RoutedStore",
    "StoreReadOnlyError",
    "default_store",
    "fingerprint",
]
