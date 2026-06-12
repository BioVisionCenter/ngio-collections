"""LocalStore: plain paths and file:// URLs, FileNotFoundError contract."""

import pytest

import ome_zarr_collections as ozc


async def test_get_plain_path(tmp_path):
    target = tmp_path / "doc.json"
    target.write_bytes(b'{"ome": {}}')
    store = ozc.LocalStore()
    assert await store.get(str(target)) == b'{"ome": {}}'


async def test_get_file_url(tmp_path):
    target = tmp_path / "doc.json"
    target.write_bytes(b"data")
    store = ozc.LocalStore()
    assert await store.get(target.as_uri()) == b"data"


async def test_get_missing_raises_file_not_found(tmp_path):
    store = ozc.LocalStore()
    with pytest.raises(FileNotFoundError):
        await store.get(str(tmp_path / "absent.json"))


async def test_put_creates_parents(tmp_path):
    store = ozc.LocalStore()
    target = tmp_path / "a" / "b" / "doc.json"
    await store.put(str(target), b"payload")
    assert target.read_bytes() == b"payload"


async def test_put_then_get_round_trip(tmp_path):
    store = ozc.LocalStore()
    url = str(tmp_path / "doc.json")
    await store.put(url, b"bytes")
    assert await store.get(url) == b"bytes"
