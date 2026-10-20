"""Shared fixtures: spec-style readable UUIDs and the revision fixture documents."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ngio_collections.api import MemoryStore

FIXTURES = Path(__file__).parent / "data" / "revision"
DATA = "/data"


def mk(n: int) -> str:
    """A readable, valid UUID in the style of the revision's examples."""
    return f"0192f3a0-7c1e-7b00-9c22-{n:012x}"


def load_fixtures(store: MemoryStore, *names: str, base: str = DATA) -> None:
    """Seed `store` with every JSON document under `tests/data/revision/<name>`."""
    for name in names:
        root = FIXTURES / name
        for path in sorted(root.rglob("*.json")):
            url = f"{base}/{name}/{path.relative_to(root).as_posix()}"
            store._data[url] = json.loads(path.read_text())


@pytest.fixture
def make_id():
    """The `mk` helper as a fixture."""
    return mk


@pytest.fixture
def revision_store() -> MemoryStore:
    """A `MemoryStore` holding the collection, plate, standalone and bad fixtures."""
    store = MemoryStore()
    load_fixtures(store, "collection", "plate", "standalone", "bad")
    return store
