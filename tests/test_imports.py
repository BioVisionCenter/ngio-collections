"""Smoke tests: the public API imports and instantiates."""

import pytest

import ngio_collections as ngc


def test_public_api_complete():
    for name in ngc.__all__:
        assert getattr(ngc, name) is not None


def test_resolver_defaults():
    resolver = ngc.Resolver(ngc.LocalStore())
    assert resolver.registry is ngc.DEFAULT_REGISTRY


def test_store_protocols():
    assert isinstance(ngc.LocalStore(), ngc.ReadableStore)
    assert isinstance(ngc.LocalStore(), ngc.WritableStore)
    assert issubclass(ngc.StoreReadOnlyError, PermissionError)


def test_fsspec_store_optional_dependency():
    try:
        import fsspec  # noqa: F401

        has_fsspec = True
    except ImportError:
        has_fsspec = False

    if has_fsspec:
        assert ngc.FsspecStore("https").protocol == "https"
    else:
        with pytest.raises(ImportError, match="fsspec"):
            ngc.FsspecStore("https")


def test_reference_fixtures_exist(reference):
    name, directory = reference
    assert (directory / "collection.json").is_file()
