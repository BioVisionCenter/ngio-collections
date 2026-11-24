"""A store that dispatches on URL scheme: local paths to one backend, http to another.

Stores are URL-addressed, so routing is pure composition. The default store the
API uses when none is given is a `RoutedStore` over `LocalStore` and
`HttpStore`, which lets a local collection whose nodes point at remote documents
resolve in one `open_resolved` call. Writes only ever go to the local backend.
"""

from __future__ import annotations

from ngio_collections._types import JSONValue
from ngio_collections.io.store._http import HttpStore
from ngio_collections.io.store._local import LocalStore
from ngio_collections.io.store._protocols import (
    AsyncReadableStore,
    AsyncWritableStore,
    StoreReadOnlyError,
)
from ngio_collections.models._paths import is_http


class RoutedStore:
    """Route each URL to the local or the http backend by its scheme."""

    def __init__(
        self,
        *,
        local: AsyncWritableStore | None = None,
        http: AsyncReadableStore | None = None,
    ) -> None:
        """Compose a `local` (writable) and an `http` (read-only) backend."""
        self.local: AsyncWritableStore = local if local is not None else LocalStore()
        self.http: AsyncReadableStore = http if http is not None else HttpStore()

    @property
    def read_only(self) -> bool:
        """Whether the local backend rejects writes."""
        return bool(getattr(self.local, "read_only", False))

    def route(self, url: str) -> AsyncReadableStore:
        """Return the backend that serves `url`."""
        return self.http if is_http(url) else self.local

    async def get(self, url: str) -> dict[str, JSONValue]:
        """Read `url` through the backend its scheme selects."""
        return await self.route(url).get(url)

    async def put(
        self, url: str, data: dict[str, JSONValue], *, overwrite: bool = False
    ) -> None:
        """Write `url` through the local backend; http destinations are read-only."""
        if is_http(url):
            raise StoreReadOnlyError(f"cannot write to remote URL {url!r}")
        await self.local.put(url, data, overwrite=overwrite)

    async def delete(self, url: str) -> None:
        """Delete `url` through the local backend; http destinations are read-only."""
        if is_http(url):
            raise StoreReadOnlyError(f"cannot delete remote URL {url!r}")
        await self.local.delete(url)


def default_store() -> RoutedStore:
    """Return the store the API uses when a caller passes none."""
    return RoutedStore()
