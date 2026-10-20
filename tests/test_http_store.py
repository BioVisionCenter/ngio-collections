"""Tests for `HttpStore` (no network: `urlopen` is monkeypatched) and routing."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

import ngio_collections as ngc
from ngio_collections.io.store import _http
from ngio_collections.io.store._local import _to_path


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _fake_urlopen(documents: dict[str, dict]):
    def urlopen(request, timeout=None):
        url = request.full_url
        if url not in documents:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        return _Response(json.dumps(documents[url]).encode())

    return urlopen


async def test_http_store_reads_and_is_read_only(monkeypatch) -> None:
    docs = {"https://h.org/a.json": {"ome": {"type": "collection"}}}
    monkeypatch.setattr(_http.urllib.request, "urlopen", _fake_urlopen(docs))
    store = ngc.HttpStore()
    assert store.read_only
    assert await store.get("https://h.org/a.json") == docs["https://h.org/a.json"]
    with pytest.raises(FileNotFoundError):
        await store.get("https://h.org/missing.json")
    with pytest.raises(ValueError):
        await store.get("/local/a.json")
    with pytest.raises(ngc.StoreReadOnlyError):
        await store.put("https://h.org/a.json", {})
    with pytest.raises(ngc.StoreReadOnlyError):
        await store.delete("https://h.org/a.json")


async def test_routed_store_dispatches_by_scheme() -> None:
    local, remote = (
        ngc.MemoryStore({"/a.json": {"l": 1}}),
        ngc.MemoryStore({"https://h.org/a.json": {"r": 1}}),
    )
    routed = ngc.RoutedStore(local=local, http=remote)
    assert await routed.get("/a.json") == {"l": 1}
    assert await routed.get("https://h.org/a.json") == {"r": 1}
    await routed.put("/b.json", {"b": 1})
    assert await local.get("/b.json") == {"b": 1}
    with pytest.raises(ngc.StoreReadOnlyError):
        await routed.put("https://h.org/b.json", {})
    await routed.delete("/b.json")
    assert not await local.contains("/b.json")
    assert not routed.read_only
    assert ngc.RoutedStore(local=ngc.MemoryStore(read_only=True)).read_only


def test_default_store_is_routed() -> None:
    from ngio_collections.io.store import default_store

    store = default_store()
    assert isinstance(store, ngc.RoutedStore)
    assert isinstance(store.local, ngc.LocalStore) and isinstance(
        store.http, ngc.HttpStore
    )


def test_local_store_rejects_remote_urls() -> None:
    with pytest.raises(ValueError):
        _to_path("https://h.org/a.json")
    assert str(_to_path("file:///p/a.json")) == "/p/a.json"
