"""Smoke tests: the public API imports and instantiates."""

import pytest

import ome_zarr_collections as ozc


def test_public_api_complete():
    for name in ozc.__all__:
        assert getattr(ozc, name) is not None


def test_resolver_defaults():
    resolver = ozc.Resolver(ozc.LocalStore())
    assert resolver.registry is ozc.DEFAULT_REGISTRY


def test_store_protocols():
    assert isinstance(ozc.LocalStore(), ozc.ReadableStore)
    assert isinstance(ozc.LocalStore(), ozc.WritableStore)
    assert issubclass(ozc.StoreReadOnlyError, PermissionError)


def test_fsspec_store_optional_dependency():
    try:
        import fsspec  # noqa: F401

        has_fsspec = True
    except ImportError:
        has_fsspec = False

    if has_fsspec:
        assert ozc.FsspecStore("https").protocol == "https"
    else:
        with pytest.raises(ImportError, match="fsspec"):
            ozc.FsspecStore("https")


def test_reference_fixtures_exist(reference):
    name, directory = reference
    assert (directory / "collection.json").is_file()
