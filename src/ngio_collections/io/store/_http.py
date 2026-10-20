"""Read-only HTTP store on the standard library (`urllib`).

Part of this package's documented deviation from RFC-8 revision 1: `http`
format paths resolve, so a local collection can point at published documents
and arrays. This store is deliberately minimal (GET only, no authentication, no
retries); `FsspecStore` is the seam for anything richer.
"""

from __future__ import annotations

import asyncio
import urllib.error
import urllib.request
from typing import Mapping

from ngio_collections._types import JSONValue
from ngio_collections.io import _json
from ngio_collections.io.store._protocols import StoreReadOnlyError
from ngio_collections.models._paths import is_http


class HttpStore:
    """Read-only store over `http://` / `https://` URLs."""

    read_only = True

    def __init__(
        self, *, timeout: float = 30.0, headers: Mapping[str, str] | None = None
    ) -> None:
        """Configure the request `timeout` (seconds) and extra request `headers`."""
        self.timeout = timeout
        self.headers = dict(headers or {})

    def _fetch(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(url) from exc
            raise

    async def get(self, url: str) -> dict[str, JSONValue]:
        """Return the parsed JSON document at `url`.

        The blocking request runs on a worker thread so concurrent `get` calls
        overlap, as `LocalStore` does for file reads.

        Args:
            url: An `http://` or `https://` URL.

        Returns:
            The document's parsed JSON content.

        Raises:
            ValueError: If `url` is not an http(s) URL.
            FileNotFoundError: If the server answers 404.
        """
        if not is_http(url):
            raise ValueError(f"HttpStore only reads http(s) URLs, got {url!r}")
        raw = await asyncio.to_thread(self._fetch, url)
        return _json.loads(raw)

    async def put(
        self, url: str, data: dict[str, JSONValue], *, overwrite: bool = False
    ) -> None:
        """Always raise: this store is read-only."""
        raise StoreReadOnlyError("HttpStore is read-only")

    async def delete(self, url: str) -> None:
        """Always raise: this store is read-only."""
        raise StoreReadOnlyError("HttpStore is read-only")
