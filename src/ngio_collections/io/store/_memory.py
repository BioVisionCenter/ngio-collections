"""In-memory store: a `url -> bytes` dict behind the store protocols.

For hermetic tests and for consumers that hold documents in memory (a cache, a
mirror, a database of documents) and want the ordinary `open`/`create`/`save`
verbs over them without touching a filesystem.
"""

from __future__ import annotations

from typing import Iterator, Mapping, AsyncIterator, Self

from ngio_collections.io.store._protocols import StoreReadOnlyError
from ngio_collections._types import JSONValue


class MemoryStore:
    """Writable in-memory store over a plain `url -> bytes` mapping."""

    def __init__(
        self,
        initial: Mapping[str, bytes] | None = None,
        *,
        read_only: bool = False,
    ) -> None:
        """Start from a copy of `initial` (empty by default).

        Args:
            initial: Seed documents, keyed by their full metadata-file URL.
            read_only: Whether `put` / `delete` raise `StoreReadOnlyError`.
        """
        self._data: dict[str, bytes] = dict(initial) if initial else {}
        self.read_only = read_only

    def _check_writable(self) -> None:
        if self.read_only:
            raise StoreReadOnlyError("MemoryStore is read-only")

    async def get(self, url: str) -> bytes:
        """Return the bytes stored at `url`.

        Raises:
            FileNotFoundError: If nothing is stored at `url`.
        """
        try:
            return self._data[url]
        except KeyError as exc:
            raise FileNotFoundError(url) from exc

    async def put(self, url: str, data: bytes) -> None:
        """Store `data` at `url`.

        Raises:
            StoreReadOnlyError: If the store is read-only.
        """
        self._check_writable()
        self._data[url] = data

    async def delete(self, url: str) -> None:
        """Remove the entry at `url`; idempotent (a missing URL is fine).

        Raises:
            StoreReadOnlyError: If the store is read-only.
        """
        self._check_writable()
        self._data.pop(url, None)

    async def items(self: Self) -> AsyncIterator[tuple[str, bytes]]:
        """Iterate over a snapshot of the stored `(url, bytes)` pairs."""
        for url, document in self._data.items():
            yield (url, document)

    async def contains(self, url: object) -> bool:
        """Return whether `url` has stored bytes."""
        return url in self._data

    async def size(self) -> int:
        """Return the number of stored documents."""
        return len(self._data)
