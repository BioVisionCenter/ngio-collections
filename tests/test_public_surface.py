"""The top-level facade is the public API: everything in `__all__` resolves."""

from __future__ import annotations

import ngio_collections as ngc
from tests.conftest import requires_pydantic


@requires_pydantic  # the typed value models resolve lazily and need pydantic
def test_all_names_resolve() -> None:
    assert ngc.__all__
    for name in ngc.__all__:
        assert getattr(ngc, name, None) is not None, name


def test_facade_covers_the_downstream_essentials() -> None:
    essentials = [
        "Node",
        "new_node",
        "new_collection",
        "new_multiscale",
        "new_id",
        "wrap_node",
        "register_node_type",
        "register_extension",
        "ReferenceObj",
        "DocPath",
        "ZarrPath",
        "open",
        "open_resolved",
        "open_ref",
        "resolve_ref",
        "create",
        "save",
        "externalize",
        "delete",
        "LocalStore",
        "MemoryStore",
        "HttpStore",
        "RoutedStore",
        "AsyncReadableStore",
        "AsyncWritableStore",
        "StoreReadOnlyError",
        "CORE_VALIDATORS",
        "RECOMMENDED_VALIDATORS",
        "ALL_VALIDATORS",
        "paths_are_core",
        "WellTrait",
        "PlateTrait",
        "LabelsTrait",
        "SceneTrait",
        "Scale",
        "CoordinateSystem",
    ]
    for name in essentials:
        assert name in ngc.__all__, name


def test_published_rfc8_names_are_gone() -> None:
    for name in (
        "SinglescaleNode",
        "Reference",
        "save_inlined",
        "open_inlined",
        "WellAttribute",
        "IdStr",
    ):
        assert name not in ngc.__all__, name
