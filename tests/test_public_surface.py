"""The top-level facade is the public API: everything in `__all__` resolves."""

from __future__ import annotations

import ngio_collections as ngc


def test_all_names_resolve() -> None:
    assert ngc.__all__
    for name in ngc.__all__:
        assert getattr(ngc, name, None) is not None, name


def test_facade_covers_the_downstream_essentials() -> None:
    # the names a downstream library builds on must never fall off the facade
    essentials = [
        "Node",
        "new_node",
        "wrap_node",
        "register_node_type",
        "Reference",
        "ReferenceObj",
        "open",
        "open_inlined",
        "create",
        "save",
        "delete",
        "LocalStore",
        "MemoryStore",
        "AsyncReadableStore",
        "AsyncWritableStore",
        "StoreReadOnlyError",
    ]
    for name in essentials:
        assert name in ngc.__all__, name
