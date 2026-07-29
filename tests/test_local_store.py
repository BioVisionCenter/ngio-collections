"""Tests for `LocalStore`: the store contract over the filesystem."""

from __future__ import annotations

import pytest

from ngio_collections.io.store import LocalStore, StoreDuplicateValueError


async def test_put_get_delete_roundtrip(tmp_path) -> None:
    store = LocalStore()
    path = tmp_path / "nested" / "a.json"

    await store.put(str(path), {"data": True})
    assert await store.get(str(path)) == {"data": True}

    await store.delete(str(path))
    await store.delete(str(path))  # idempotent
    with pytest.raises(FileNotFoundError):
        await store.get(str(path))


async def test_put_rejects_existing_file_without_overwrite(tmp_path) -> None:
    store = LocalStore()
    path = tmp_path / "a.json"

    await store.put(str(path), {"seed": True})
    with pytest.raises(StoreDuplicateValueError):
        await store.put(str(path), {"clobber": True})
    assert await store.get(str(path)) == {"seed": True}

    await store.put(str(path), {"clobber": True}, overwrite=True)
    assert await store.get(str(path)) == {"clobber": True}
