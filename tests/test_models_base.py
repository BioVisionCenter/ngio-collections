"""Models base layer: aliasing, round-trip fidelity, paths, attrs view,
provenance defaults."""

import pytest
from pydantic import TypeAdapter, ValidationError

import ngio_collections as ngc
from ngio_collections.models import AttrsView, PathObj


def test_camel_case_aliasing():
    class Obj(ngc.BaseObj):
        coordinate_systems: list[str]

    obj = Obj.model_validate({"coordinateSystems": ["cs-1"]})
    assert obj.coordinate_systems == ["cs-1"]
    assert obj.model_dump(by_alias=True) == {"coordinateSystems": ["cs-1"]}
    # populate_by_name: snake_case input also accepted
    assert Obj(coordinate_systems=["cs-1"]).coordinate_systems == ["cs-1"]


def test_extra_fields_round_trip():
    data = {
        "type": "collection",
        "id": "root",
        "name": "root",
        "x-custom:field": {"a": 1},
    }
    node = ngc.BaseNode.model_validate(data)
    dumped = node.model_dump(by_alias=True, exclude_none=True)
    assert dumped["x-custom:field"] == {"a": 1}


def test_id_pattern():
    ngc.BaseNode(type="t", id="a-Z_0.9", name="n")
    with pytest.raises(ValidationError):
        ngc.BaseNode(type="t", id="not/allowed", name="n")


def test_name_is_optional():
    node = ngc.BaseNode(type="t", id="x")
    assert node.name is None


def test_new_generates_unique_id():
    a = ngc.BaseNode.new(type="t", name="a")
    b = ngc.BaseNode.new(type="t", name="b")
    assert a.id != b.id
    # Generated ids satisfy IdStr's pattern.
    ngc.BaseNode(type="t", id=a.id, name="a")

    # An explicit id is respected, not overridden.
    explicit = ngc.BaseNode.new(type="t", id="custom", name="c")
    assert explicit.id == "custom"


def test_path_discriminated_union():
    adapter = TypeAdapter(PathObj)
    zarr = adapter.validate_python({"type": "zarr", "path": "img.zarr"})
    json_ = adapter.validate_python({"type": "json", "path": "doc.json"})
    assert isinstance(zarr, ngc.ZarrPath)
    assert isinstance(json_, ngc.JsonPath)
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "csv", "path": "x.csv"})


def test_node_has_no_version_field():
    # `version` lives on MetadataDocument, not on the node model (DESIGN.md §3.1).
    assert "version" not in ngc.BaseNode.model_fields


@pytest.fixture
def well_node():
    return ngc.BaseNode(
        type="well",
        id="well-A1",
        name="A1",
        attributes={"well": {"column": {"id": "1"}, "row": {"id": "A"}}},
    )


def test_attrs_view_read(well_node):
    assert isinstance(well_node.attrs, AttrsView)
    assert ngc.WellAttribute in well_node.attrs
    well = well_node.attrs[ngc.WellAttribute]
    assert well.column.id == "1"
    assert well.row.id == "A"


def test_attrs_view_missing(well_node):
    assert ngc.PlateAttribute not in well_node.attrs
    with pytest.raises(KeyError):
        well_node.attrs[ngc.PlateAttribute]
    assert well_node.attrs.get(ngc.PlateAttribute) is None


def test_attrs_view_write_back(well_node):
    well = well_node.attrs[ngc.WellAttribute]
    well.column.id = "2"
    # mutating the view does nothing until explicit write-back
    assert well_node.attributes["well"]["column"]["id"] == "1"
    well_node.attrs[ngc.WellAttribute] = well
    assert well_node.attributes["well"]["column"]["id"] == "2"


def test_attrs_view_delete(well_node):
    del well_node.attrs[ngc.WellAttribute]
    assert ngc.WellAttribute not in well_node.attrs


def test_attrs_view_write_validates():
    node = ngc.BaseNode(type="t", id="x", name="n")
    with pytest.raises(ValidationError):
        node.attrs[ngc.WellAttribute] = {"column": {"id": "not/valid"}}


def test_attrs_view_stays_live_after_attributes_reassignment(well_node):
    view = well_node.attrs
    well_node.attributes = {"well": {"column": {"id": "9"}, "row": {"id": "Z"}}}
    assert view[ngc.WellAttribute].column.id == "9"


def test_merged_attributes_stub_wins():
    stub = ngc.BaseNode(
        type="t",
        id="x",
        name="n",
        path=ngc.JsonPath(path="./child.json"),
        attributes={"shared": "from-stub", "stubOnly": 2},
    )
    target_root = ngc.BaseNode(
        type="t",
        id="x",
        name="n",
        attributes={"shared": "from-target", "targetOnly": 1},
    )
    merged = ngc.merged_attributes(stub, target_root)
    assert merged == {"shared": "from-stub", "targetOnly": 1, "stubOnly": 2}
    # A fresh dict: neither side is mutated through the result.
    merged["injected"] = True
    assert "injected" not in stub.attributes
    assert "injected" not in target_root.attributes


def test_provenance_defaults_to_detached():
    node = ngc.BaseNode(type="t", id="x", name="n")
    assert node._document is None
    assert node._parent is None
    # re-validation produces a detached node
    revalidated = ngc.BaseNode.model_validate(node.model_dump(by_alias=True))
    assert revalidated._document is None


def test_target_url_none_without_path():
    node = ngc.BaseNode(type="t", id="x", name="n")
    assert node.target_url is None


def test_target_url_detached_raises():
    node = ngc.BaseNode(type="t", id="x", name="n", path=ngc.ZarrPath(path="./s0"))
    with pytest.raises(ValueError, match="detached"):
        node.target_url


def _parsed_root(path: str, url: str) -> ngc.BaseNode:
    doc = ngc.parse_metadata_document(
        {
            "ome": {
                "version": "0.x",
                "type": "collection",
                "id": "root",
                "name": "root",
                "nodes": [
                    {
                        "type": "multiscale",
                        "id": "child",
                        "name": "child",
                        "path": {"type": "zarr", "path": path},
                    }
                ],
            }
        },
        url=url,
    )
    return doc.root


def test_target_url_joins_document_relative_path():
    # json form: relative paths are siblings of the document
    root = _parsed_root("./image.zarr", url="/data/collection.json")
    assert root.nodes[0].target_url == "/data/image.zarr"


def test_target_url_zarr_form_resolves_inside_group():
    zarr_doc = {
        "zarr_format": 3,
        "node_type": "group",
        "attributes": {
            "ome": {
                "version": "0.x",
                "type": "multiscale",
                "id": "image",
                "name": "image",
                "nodes": [
                    {
                        "type": "singlescale",
                        "id": "s0",
                        "name": "s0",
                        "path": {"type": "zarr", "path": "./s0"},
                    }
                ],
                "attributes": {"coordinateSystems": []},
            }
        },
    }
    doc = ngc.parse_metadata_document(zarr_doc, url="/data/image.zarr/zarr.json")
    assert doc.root.nodes[0].target_url == "/data/image.zarr/s0"


def test_target_url_absolute_path_passes_through():
    root = _parsed_root("/elsewhere/image.zarr", url="/data/collection.json")
    assert root.nodes[0].target_url == "/elsewhere/image.zarr"


def test_target_path_of_pathless_node_is_its_source_document():
    # A parsed pathless node points at the document it was declared in.
    root = _parsed_root("./image.zarr", url="/data/collection.json")
    assert root.path is None
    assert isinstance(root.target_path, ngc.JsonPath)
    assert root.target_path.path == "/data/collection.json"
    assert root.target_url == "/data/collection.json"


def test_target_path_of_pathless_node_in_zarr_document():
    doc = ngc.parse_metadata_document(
        {
            "zarr_format": 3,
            "node_type": "group",
            "attributes": {
                "ome": {
                    "version": "0.x",
                    "type": "multiscale",
                    "id": "image",
                    "name": "image",
                    "nodes": [
                        {
                            "type": "singlescale",
                            "id": "s0",
                            "name": "s0",
                            "path": {"type": "zarr", "path": "./s0"},
                        }
                    ],
                    "attributes": {"coordinateSystems": []},
                }
            },
        },
        url="/data/image.zarr/zarr.json",
    )
    # A zarr-form document is addressed by its group directory.
    assert isinstance(doc.root.target_path, ngc.ZarrPath)
    assert doc.root.target_path.path == "/data/image.zarr"


def test_target_path_preserves_type_for_path_bearing_node():
    root = _parsed_root("./image.zarr", url="/data/collection.json")
    child = root.nodes[0]
    assert isinstance(child.target_path, ngc.ZarrPath)
    assert child.target_path.path == "/data/image.zarr"
    assert child.target_url == child.target_path.path


def test_attribute_namespace():
    class VendorAttribute(ngc.BaseAttribute):
        key = "acme:thing"

    assert VendorAttribute.name_space() == "acme"
    assert ngc.PlateAttribute.name_space() is None
