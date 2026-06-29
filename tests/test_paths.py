"""Path mechanics: resolve / relativize are inverses keyed off one base URL.

`relativize(target, base)` rewrites an absolute local target to a path relative
to `dirname(base)`; `resolve(rel, base)` walks it back. They must round-trip, and
must agree for both a JSON base (the document file) and a Zarr base (the
`zarr.json` inside the group dir). Remote / cross-root targets stay absolute.
"""

import pytest

from ngio_collections.models._paths import (
    DocPath,
    JsonPath,
    ZarrPath,
    meta_url,
    relativize,
    resolve,
    split_scheme,
)

# A JSON document lives at its file; a Zarr document at <group>/zarr.json. The
# relativization base is dirname(base_url) in both cases.
JSON_BASE = "/p/mdc/collection.json"
ZARR_BASE = "/p/mdc/labels.zarr/zarr.json"


@pytest.mark.parametrize("base", [JSON_BASE, ZARR_BASE])
@pytest.mark.parametrize(
    "target, expected_for",
    [
        # (absolute target, {base_url: expected relative form})
        ("/p/mdc/image.zarr", {JSON_BASE: "./image.zarr", ZARR_BASE: "../image.zarr"}),
        (
            "/p/mdc/labels.zarr/sub/x.zarr",
            {JSON_BASE: "./labels.zarr/sub/x.zarr", ZARR_BASE: "./sub/x.zarr"},
        ),
        ("/p/top.zarr", {JSON_BASE: "../top.zarr", ZARR_BASE: "../../top.zarr"}),
    ],
)
def test_relativize_roundtrips(base, target, expected_for):
    rel = relativize(target, base)
    assert rel == expected_for[base]
    # The whole point: resolve undoes relativize for the same base.
    assert resolve(rel, base) == target


@pytest.mark.parametrize("base", [JSON_BASE, ZARR_BASE])
@pytest.mark.parametrize(
    "target",
    [
        "/other/tree/x.zarr",  # cross-root: nothing shared but "/"
        "http://h.org/x.zarr",  # remote
        "https://h.org/x.zarr",
        "file:///p/mdc/image.zarr",  # file:// kept absolute (still resolves)
    ],
)
def test_relativize_keeps_non_local_or_cross_root_absolute(base, target):
    assert relativize(target, base) == target


def test_intra_group_array_path_passes_through():
    # `./0` is already relative -> untouched on write, resolves group-relative.
    assert relativize("./0", ZARR_BASE) == "./0"
    assert resolve("./0", ZARR_BASE) == "/p/mdc/labels.zarr/0"


def test_resolve_walks_parents_for_both_forms():
    assert resolve("../image.zarr", ZARR_BASE) == "/p/mdc/image.zarr"
    assert resolve("../../top.zarr", ZARR_BASE) == "/p/top.zarr"
    assert resolve("./image.zarr", JSON_BASE) == "/p/mdc/image.zarr"


def test_resolve_absolute_and_remote_passthrough():
    assert resolve("/abs/x.zarr", None) == "/abs/x.zarr"
    assert resolve("http://h.org/x", None) == "http://h.org/x"
    with pytest.raises(ValueError):
        resolve("./x", None)  # relative needs a base


def test_relativize_none_base_keeps_path():
    assert relativize("/p/mdc/image.zarr", None) == "/p/mdc/image.zarr"


def test_meta_url():
    assert meta_url("/p/g.zarr") == "/p/g.zarr/zarr.json"
    assert meta_url("/p/g.zarr/") == "/p/g.zarr/zarr.json"
    assert meta_url("/p/g.zarr/zarr.json") == "/p/g.zarr/zarr.json"
    assert meta_url("/p/c.json") == "/p/c.json"


def test_split_scheme():
    assert split_scheme("/p/x") == ("", "/p/x")
    assert split_scheme("file:///p/x") == ("file", "/p/x")
    assert split_scheme("https://h.org/x") == ("https", "h.org/x")


def test_docpath_methods_and_subclasses():
    p = ZarrPath(path="/p/mdc/image.zarr")
    assert p.type == "zarr"
    rel = p.relativize(ZARR_BASE)
    assert (rel.type, rel.path) == ("zarr", "../image.zarr")
    assert rel.resolve(ZARR_BASE) == "/p/mdc/image.zarr"
    assert JsonPath(path="./c.json").type == "json"
    assert DocPath(type="json", path="./c.json").type == "json"
