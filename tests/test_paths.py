"""Path objects: `{type, format, href}` with explicit formats and no inference.

`relativize(href, base)` rewrites an absolute local href relative to
`dirname(base)` and labels it `relative`; `resolve(rel, "relative", base)` walks
it back. They must round-trip for both a JSON base (the document file) and a
Zarr base (the `zarr.json` inside the group dir). `absolute` and `http` hrefs
pass through verbatim by default (this package's documented deviation) and
raise under `CORE_FORMATS`.
"""

import pytest

from ngio_collections.models._paths import (
    ALL_FORMATS,
    BUILTIN_PATH_TYPES,
    CORE_FORMATS,
    DocPath,
    JsonPath,
    UnsupportedPathFormatError,
    ZarrPath,
    format_for_url,
    is_http,
    meta_url,
    relativize,
    resolve,
    split_scheme,
)

JSON_BASE = "/p/mdc/collection.json"
ZARR_BASE = "/p/mdc/labels.zarr/zarr.json"


@pytest.mark.parametrize("base", [JSON_BASE, ZARR_BASE])
@pytest.mark.parametrize(
    "target, expected_for",
    [
        ("/p/mdc/image.zarr", {JSON_BASE: "./image.zarr", ZARR_BASE: "../image.zarr"}),
        (
            "/p/mdc/labels.zarr/sub/x.zarr",
            {JSON_BASE: "./labels.zarr/sub/x.zarr", ZARR_BASE: "./sub/x.zarr"},
        ),
        ("/p/top.zarr", {JSON_BASE: "../top.zarr", ZARR_BASE: "../../top.zarr"}),
    ],
)
def test_relativize_roundtrips(base, target, expected_for):
    fmt, rel = relativize(target, base)
    assert (fmt, rel) == ("relative", expected_for[base])
    assert resolve(rel, "relative", base) == target


@pytest.mark.parametrize("base", [JSON_BASE, ZARR_BASE])
@pytest.mark.parametrize(
    "target",
    ["/other/tree/x.zarr", "file:///p/mdc/image.zarr"],
)
def test_relativize_keeps_cross_root_and_file_urls_absolute(base, target):
    assert relativize(target, base) == ("absolute", target)


def test_relativize_none_base_keeps_path():
    assert relativize("/p/mdc/image.zarr", None) == ("absolute", "/p/mdc/image.zarr")


def test_resolve_by_declared_format_never_by_string():
    assert resolve("./image.zarr", "relative", JSON_BASE) == "/p/mdc/image.zarr"
    assert resolve("../../top.zarr", "relative", ZARR_BASE) == "/p/top.zarr"
    assert resolve("/abs/x.zarr", "absolute", None) == "/abs/x.zarr"
    assert resolve("https://h.org/x", "http", None) == "https://h.org/x"
    with pytest.raises(ValueError):
        resolve("./x", "relative", None)  # relative needs a base


def test_core_formats_opt_in_rejects_absolute_and_http():
    assert ALL_FORMATS == {"relative", "absolute", "http"}
    assert CORE_FORMATS == {"relative"}
    with pytest.raises(UnsupportedPathFormatError):
        resolve("/abs/x.zarr", "absolute", JSON_BASE, formats=CORE_FORMATS)
    with pytest.raises(UnsupportedPathFormatError):
        DocPath(type="zarr", format="http", href="https://h.org/x").resolve(
            JSON_BASE, formats=CORE_FORMATS
        )
    assert (
        resolve("/abs/x.zarr", "absolute", JSON_BASE, formats=ALL_FORMATS)
        == "/abs/x.zarr"
    )


def test_meta_url_for_entry_locations():
    assert meta_url("/p/g.zarr") == "/p/g.zarr/zarr.json"
    assert meta_url("/p/g.zarr/") == "/p/g.zarr/zarr.json"
    assert meta_url("/p/g.zarr/zarr.json") == "/p/g.zarr/zarr.json"
    assert meta_url("/p/c.json") == "/p/c.json"


def test_docpath_meta_url_is_keyed_on_type():
    zarr = ZarrPath(href="./raw")
    assert zarr.meta_url(ZARR_BASE) == "/p/mdc/labels.zarr/raw/zarr.json"
    json_doc = JsonPath(href="./child/collection.json")
    assert json_doc.meta_url(JSON_BASE) == "/p/mdc/child/collection.json"
    # an href that already names the metadata file is not doubled
    assert (
        ZarrPath(href="./raw/zarr.json").meta_url(JSON_BASE) == "/p/mdc/raw/zarr.json"
    )


def test_docpath_relativize_only_touches_local_absolute_paths():
    local = DocPath(type="zarr", format="absolute", href="/p/mdc/image.zarr")
    rel = local.relativize(ZARR_BASE)
    assert (rel.format, rel.href) == ("relative", "../image.zarr")
    assert rel.resolve(ZARR_BASE) == "/p/mdc/image.zarr"
    remote = DocPath(type="zarr", format="http", href="https://h.org/x.zarr")
    assert remote.relativize(ZARR_BASE) is remote
    already = ZarrPath(href="./0")
    assert already.relativize(ZARR_BASE) is already


def test_for_url_picks_type_and_format():
    p = DocPath.for_url("/data/image.zarr/zarr.json")
    assert (p.type, p.format, p.href) == ("zarr", "absolute", "/data/image.zarr")
    assert DocPath.for_url("/data/image.zarr").href == "/data/image.zarr"
    j = DocPath.for_url("/data/c.json")
    assert (j.type, j.format, j.href) == ("json", "absolute", "/data/c.json")
    h = DocPath.for_url("https://h.org/ref.ome.zarr")
    assert (h.type, h.format, h.href) == ("zarr", "http", "https://h.org/ref.ome.zarr")


def test_docpath_rejects_inconsistent_format_and_href():
    with pytest.raises(ValueError):
        DocPath(type="zarr", format="http", href="/local/path")
    with pytest.raises(ValueError):
        DocPath(type="zarr", format="relative", href="https://h.org/x")
    with pytest.raises(ValueError):
        DocPath.from_dict({"type": "zarr", "href": "./x"})  # format is required
    with pytest.raises(ValueError):
        DocPath(type="tiff", format="relative", href="./x")  # not a URI either
    with pytest.raises(ValueError):
        DocPath.from_dict("./x")  # type: ignore[arg-type]


def test_docpath_accepts_extension_uri_types_as_data_paths():
    csv = "https://ext.example/fractal/csv"
    assert BUILTIN_PATH_TYPES == {"zarr", "json"}
    data = DocPath.from_dict({"type": csv, "format": "relative", "href": "./t.csv"})
    assert data.type == csv and not data.is_document
    assert ZarrPath(href="./s0").is_document and JsonPath(href="./c.json").is_document
    # it resolves and relativizes like any path, but is not a document
    assert data.resolve(JSON_BASE) == "/p/mdc/t.csv"
    with pytest.raises(ValueError):
        data.meta_url(JSON_BASE)
    absolute = DocPath(type=csv, format="absolute", href="/p/mdc/tables/t.csv")
    rel = absolute.relativize(JSON_BASE)
    assert (rel.type, rel.format, rel.href) == (csv, "relative", "./tables/t.csv")
    assert data.to_dict() == {"type": csv, "format": "relative", "href": "./t.csv"}


def test_docpath_dict_round_trip_is_a_closed_shape():
    wire = {"type": "zarr", "format": "relative", "href": "./x"}
    path = DocPath.from_dict(wire)
    assert path == DocPath(type="zarr", format="relative", href="./x")
    assert path.to_dict() == wire == ZarrPath(href="./x").to_dict()
    assert DocPath.from_dict(path) is path
    # unknown keys are not kept: the path-object shape is closed
    assert DocPath.from_dict({**wire, "weird": 1}).to_dict() == wire


def test_convenience_subclasses_default_to_relative():
    assert ZarrPath(href="./s0").to_dict() == {
        "type": "zarr",
        "format": "relative",
        "href": "./s0",
    }
    assert JsonPath(href="./c.json").type == "json"
    assert ZarrPath(format="http", href="https://h.org/a").format == "http"


def test_scheme_helpers():
    assert split_scheme("/p/x") == ("", "/p/x")
    assert split_scheme("file:///p/x") == ("file", "/p/x")
    assert split_scheme("https://h.org/x") == ("https", "h.org/x")
    assert is_http("https://h.org/x") and not is_http("/p/x")
    assert format_for_url("https://h.org/x") == "http"
    assert format_for_url("/p/x") == "absolute"
