"""IO layer: the URL-addressed store backends and protocols.

The only IO surface of the package. JSON (de)serialization lives in `_json`; the
resolution / read-write orchestration is the v5 `resolve` and `api` layers.
"""

from ngio_collections.io.store import (
    FsspecStore,
    LocalStore,
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
