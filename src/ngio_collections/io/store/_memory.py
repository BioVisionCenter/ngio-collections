"""In-memory store: a `url -> dict` dict behind the store protocols.

For hermetic tests and for consumers that hold documents in memory (a cache, a
mirror, a database of documents) and want the ordinary `open`/`create`/`save`
verbs over them without touching a filesystem.
"""

from __future__ import annotations

from typing import Iterator, Mapping, AsyncIterator, Self

from ngio_collections._types import JSONValue
from ngio_collections.io.store._protocols import (
    StoreDuplicateValueError,
    StoreReadOnlyError,
)


class MemoryStore:
    """Writable in-memory store over a plain `url -> dict` mapping."""

    def __init__(
        self,
        initial: Mapping[str, dict[str, JSONValue]] | None = None,
        *,
        read_only: bool = False,
    ) -> None:
        """Start from a copy of `initial` (empty by default).

        Args:
            initial: Seed documents, keyed by their full metadata-file URL.
            read_only: Whether `put` / `delete` raise `StoreReadOnlyError`.
        """
        self._data: dict[str, dict[str, JSONValue]] = dict(initial) if initial else {}
        self.read_only = read_only

    def _check_writable(self) -> None:
        if self.read_only:
            raise StoreReadOnlyError("MemoryStore is read-only")

    async def get(self, url: str) -> dict[str, JSONValue]:
        """Return the document stored at `url`.

        Raises:
            FileNotFoundError: If nothing is stored at `url`.
        """
        try:
            return self._data[url]
        except KeyError as exc:
            raise FileNotFoundError(url) from exc

    async def put(
        self, url: str, data: dict[str, JSONValue], *, overwrite: bool = False
    ) -> None:
        """Store `data` at `url`.

        Args:
            url: Key to store `data` under.
            data: The document's JSON content to store.
            overwrite: Whether to replace an existing entry at `url`.

        Raises:
            StoreReadOnlyError: If the store is read-only.
            StoreDuplicateValueError: If `url` is already stored and
                `overwrite` is `False`.
        """
        self._check_writable()
        if not overwrite and url in self._data:
            raise StoreDuplicateValueError(url)
        self._data[url] = data

    async def delete(self, url: str) -> None:
        """Remove the entry at `url`; idempotent (a missing URL is fine).

        Raises:
            StoreReadOnlyError: If the store is read-only.
        """
        self._check_writable()
        self._data.pop(url, None)

    async def items(self: Self) -> AsyncIterator[tuple[str, dict[str, JSONValue]]]:
        """Iterate over a snapshot of the stored `(url, dict)` pairs."""
        for url, document in self._data.items():
            yield (url, document)

    async def contains(self, url: object) -> bool:
        """Return whether `url` has a stored document."""
        return url in self._data

    async def size(self) -> int:
        """Return the number of stored documents."""
        return len(self._data)
