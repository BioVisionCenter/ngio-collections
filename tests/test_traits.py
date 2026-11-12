"""Validation tests for the typed value models (decoupled from nodes).

Traits, multiscale fields, typed references, path objects and the extension
manifest are exercised directly via `model_validate` / construction. Node
integration is covered in `test_node.py` / `test_validate.py`.
"""

from __future__ import annotations

import json

import pytest

import ngio_collections as ngc
from ngio_collections.models._manifest import manifest_entries
from tests.conftest import FIXTURES, mk

# The whole module is about the typed models: skip it without pydantic.
ValidationError = pytest.importorskip("pydantic").ValidationError


def test_plate_trait_follows_the_revision_example() -> None:
    plate_doc = json.loads((FIXTURES / "plate" / "zarr.json").read_text())
    (plate_raw,) = plate_doc["attributes"]["ome"]["traits"]
    plate = ngc.PlateTrait.model_validate(plate_raw)
    assert [r.name for r in plate.rows] == ["A", "B"]
    assert [c.name for c in plate.columns] == ["1", "2"]
    (acq,) = plate.acquisitions
    assert acq.type == "acquisition" and acq.id == mk(0xB) and acq.name == "t0"
    assert ngc.PlateTrait.trait_type() == "plate"
    assert ngc.PlateTrait.applies_to == {"collection"}


def test_plate_requires_rows_and_columns() -> None:
    with pytest.raises(ValidationError):
        ngc.PlateTrait.model_validate({"type": "plate", "rows": [{"name": "A"}]})


def test_well_trait_is_indices_not_references() -> None:
    well = ngc.WellTrait.model_validate(
        {"type": "well", "row_index": 0, "column_index": 3}
    )
    assert (well.row_index, well.column_index) == (0, 3)
    with pytest.raises(ValidationError):
        ngc.WellTrait(row_index=-1, column_index=0)
    assert well.model_dump(mode="json") == {
        "type": "well",
        "row_index": 0,
        "column_index": 3,
    }


def test_labels_trait_sources_are_typed_references() -> None:
    labels = ngc.LabelsTrait.model_validate(
        {
            "type": "labels",
            "source": [{"type": "multiscale", "ref": mk(2)}],
            "label_attributes": [{"label_value": 1, "rgba": [255, 0, 0, 255]}],
        }
    )
    assert isinstance(labels.source[0], ngc.ReferenceObj)
    assert labels.source[0].type == "multiscale" and labels.source[0].ref == mk(2)
    assert labels.label_attributes[0].rgba == [255, 0, 0, 255]
    assert ngc.LabelsTrait.applies_to == {"multiscale"}


def test_scene_trait_writes_the_camel_case_wire_keys() -> None:
    scene = ngc.SceneTrait.model_validate(
        {
            "type": "scene",
            "coordinateSystems": [
                {"type": "coordinate_system", "id": mk(5), "axes": [{"name": "x"}]}
            ],
            "coordinateTransformations": [
                {
                    "type": "sequence",
                    "input": {"type": "coordinate_system", "ref": mk(6)},
                    "output": {"type": "coordinate_system", "ref": mk(5)},
                    "transformations": [
                        {"type": "scale", "scale": [1.0, 1.0]},
                        {"type": "translation", "translation": [0.0, 5.0]},
                    ],
                }
            ],
        }
    )
    seq = scene.coordinate_transformations[0]
    assert isinstance(seq, ngc.SequenceTransformation)
    assert isinstance(seq.transformations[0], ngc.ScaleTransformation)
    dumped = scene.model_dump(mode="json", exclude_none=True)
    assert set(dumped) == {"type", "coordinateSystems", "coordinateTransformations"}
    # the Python attribute names are accepted on input and never written
    by_name = ngc.SceneTrait.model_validate(
        {"type": "scene", "coordinate_systems": dumped["coordinateSystems"]}
    )
    assert by_name.coordinate_systems == scene.coordinate_systems
    assert "coordinate_systems" not in by_name.model_dump(mode="json")


def test_reference_obj_is_typed_id_and_closed() -> None:
    ref = ngc.ReferenceObj(type="array", ref=mk(0xC))
    assert ref.to_dict() == {
        "type": "array",
        "ref": mk(0xC),
    }
    assert ngc.ReferenceObj(type="array", ref="s0").ref == "s0"  # any id
    with pytest.raises(ValueError):
        ngc.ReferenceObj(type="array", ref="s 0")  # not a valid id
    with pytest.raises(ValueError):
        ngc.ReferenceObj.from_dict({"type": "array", "ref": mk(1), "name": "x"})
    with pytest.raises(ValueError):
        ngc.ReferenceObj.from_dict({"type": "array", "id": mk(1)})  # a declaration
    with_path = ngc.ReferenceObj.from_dict(
        {
            "type": "coordinate_system",
            "ref": mk(0x20),
            "path": {"type": "zarr", "format": "relative", "href": "./raw"},
        }
    )
    assert with_path.path is not None and with_path.path.href == "./raw"


def test_multiscale_fields_validate_the_raw_fixture() -> None:
    raw = json.loads((FIXTURES / "collection" / "raw" / "zarr.json").read_text())
    ome = raw["attributes"]["ome"]
    fields = ngc.MultiscaleFields.model_validate(
        {
            k: v
            for k, v in ome.items()
            if k in ngc.models._multiscale_keys.MULTISCALE_FIELDS
        }
    )
    (physical,) = fields.coordinate_systems
    assert physical.id == mk(0x20)
    assert [a.name for a in physical.axes] == ["c", "z", "y", "x"]
    s0, s1 = fields.arrays
    assert s0.type == "array" and "id" not in s0.model_dump()
    assert s0.downsamplingTransformations is None and s0.scale is None
    assert isinstance(s0.path, ngc.DocPath) and s0.path.href == "./s0"
    assert (
        s1.scale == [1, 1, 2, 2] and s1.translation is None and s1.path.href == "./s1"
    )
    (tf,) = fields.coordinate_transformations
    assert isinstance(tf, ngc.ScaleTransformation) and tf.scale == [1, 0.5, 0.1, 0.1]
    assert tf.input is not None
    assert tf.input.type == "multiscale" and tf.input.ref == ome["id"]
    assert tf.output is not None and tf.output.ref == mk(0x20)
    # the wire form keeps the camelCase spelling of the downsampling key
    assert ngc.DOWNSAMPLING_KEY in s1.model_dump(mode="json")


def test_multiscale_array_shapes() -> None:
    both = ngc.MultiscaleArray.model_validate(
        {
            "type": "array",
            "path": {"type": "zarr", "format": "relative", "href": "./s1"},
            "downsamplingTransformations": [
                {"type": "scale", "scale": [2, 2]},
                {"type": "translation", "translation": [0.5, 0.5]},
            ],
        }
    )
    assert both.scale == [2, 2]
    assert both.translation == [0.5, 0.5]
    # the highest-resolution array carries no downsampling at all
    finest = ngc.MultiscaleArray(path=both.path)
    assert finest.scale is None and finest.translation is None
    assert ngc.DOWNSAMPLING_KEY not in finest.model_dump(exclude_none=True)
    for bad in (
        [],
        [{"type": "translation", "translation": [0.0]}],
        [  # the translation follows the scale, never the other way round
            {"type": "translation", "translation": [0.5]},
            {"type": "scale", "scale": [2.0]},
        ],
        [{"type": "scale", "scale": [1.0]}, {"type": "scale", "scale": [2.0]}],
        [{"type": "affine", "affine": []}],
    ):
        with pytest.raises(ValidationError):
            ngc.MultiscaleArray.model_validate(
                {"path": both.path.to_dict(), "downsamplingTransformations": bad}
            )
    with pytest.raises(ValidationError):  # the path is required
        ngc.MultiscaleArray.model_validate(
            {"downsamplingTransformations": [{"type": "scale", "scale": [1.0]}]}
        )
    # a remote level: the dataclass path checks surface as pydantic errors
    remote = ngc.MultiscaleArray(
        path=ngc.DocPath(type="zarr", format="http", href="https://h.org/img/0"),
        downsamplingTransformations=[ngc.ScaleDownsampling(scale=[1.0])],
    )
    assert remote.model_dump(mode="json", exclude_none=True)["path"]["format"] == "http"
    with pytest.raises(ValidationError):
        ngc.MultiscaleArray(
            path={"type": "zarr", "format": "http", "href": "/local"},
            downsamplingTransformations=[ngc.ScaleDownsampling(scale=[1.0])],
        )


def test_unknown_transformation_falls_back_to_custom_and_round_trips() -> None:
    transform = ngc.CustomTransformation.model_validate(
        {
            "type": "https://myorg.org/ngff/nonlinear",
            "input": {"type": "coordinate_system", "ref": mk(1)},
            "warp": [1, 2, 3],
        }
    )
    assert transform.type == "https://myorg.org/ngff/nonlinear"
    assert transform.warp == [1, 2, 3]  # extra="allow" keeps unknown fields


def test_trait_type_helpers() -> None:
    assert ngc.WellTrait.trait_type() == "well" and not ngc.WellTrait.is_extension()
    with pytest.raises(TypeError):
        ngc.UnknownTrait.trait_type()
    custom = ngc.UnknownTrait.model_validate(
        {"type": "https://napari.org/ngff/rendering", "contrast_limits": [0, 1]}
    )
    assert custom.type == "https://napari.org/ngff/rendering"
    assert ngc.is_extension_type(custom.type) and not ngc.is_extension_type("well")


def test_ids() -> None:
    fresh = ngc.new_id()
    assert ngc.is_id(fresh) and fresh[14] == "7"  # the default is still a UUIDv7
    assert ngc.new_id() != fresh
    assert ngc.is_id(mk(1)) and ngc.is_id("img") and ngc.is_id("well_A1.0")
    for bad in ("", "a b", "img/0", "x:y", None, 3):
        assert not ngc.is_id(bad), bad


def test_extension_manifest_registry_and_derivation() -> None:
    napari = ngc.ExtensionManifestEntry(
        id="https://napari.org/ngff/",
        version="1.0",
        schemas=[
            ngc.SchemaRef(
                type="jsonschema", url="https://napari.org/ngff/1.0/schema.json"
            )
        ],
    )
    deep = ngc.ExtensionManifestEntry(
        id="https://napari.org/ngff/rendering/", version="2"
    )
    registry = ngc.ExtensionRegistry([napari, deep])
    assert (
        registry.lookup("https://napari.org/ngff/rendering/x") is deep
    )  # longest prefix
    assert registry.lookup("https://napari.org/ngff/labels") is napari
    assert registry.lookup("https://other.org/t") is None

    used = ["well", "https://napari.org/ngff/labels", "https://other.org/t"]
    known = [{"id": "https://other.org/", "version": "0.1", "schemas": []}]
    entries = manifest_entries(used, registry=registry, known=known)
    assert [e["id"] for e in entries] == [
        "https://napari.org/ngff/",
        "https://other.org/",
    ]
    assert entries[0]["schemas"][0]["url"].endswith("schema.json")
    assert manifest_entries(["https://nobody.org/x"], registry=registry) == []


def test_extension_manifest_entry_round_trips_the_upstream_fields() -> None:
    wire = {
        "id": "https://viewer-a.example.com/settings/",
        "version": "0.1",
        "schemas": [{"type": "linkml", "url": "https://viewer-a.example.com/s.yaml"}],
        "name": "Viewer-A settings",
        "description": "Display settings for Viewer A.",
        "mustUnderstand": True,
        "homepage": "https://viewer-a.example.com/",
        "unknown": "ignored",
    }
    entry = ngc.ExtensionManifestEntry.from_dict(wire)
    assert entry.name == "Viewer-A settings" and entry.must_understand is True
    assert entry.to_dict() == {k: v for k, v in wire.items() if k != "unknown"}
    # optional fields are omitted when unset; `mustUnderstand` defaults to False
    minimal = ngc.ExtensionManifestEntry.from_dict(
        {"id": "https://x.org/", "version": "1"}
    )
    assert minimal.must_understand is False
    assert minimal.to_dict() == {"id": "https://x.org/", "version": "1", "schemas": []}
    with pytest.raises(ValueError, match="mustUnderstand"):
        ngc.ExtensionManifestEntry.from_dict(
            {"id": "https://x.org/", "version": "1", "mustUnderstand": "yes"}
        )
    with pytest.raises(ValueError, match="`name`"):
        ngc.ExtensionManifestEntry(id="https://x.org/", version="1", name=3)  # type: ignore[arg-type]


def test_dataclass_locators_work_as_pydantic_fields() -> None:
    """`DocPath` / `ReferenceObj` are stdlib dataclasses; pydantic coerces them."""
    wire = {
        "type": "labels",
        "source": [
            {
                "type": "multiscale",
                "ref": mk(2),
                "path": {"type": "zarr", "format": "relative", "href": "./raw"},
            }
        ],
        "label_attributes": [],
    }
    labels = ngc.LabelsTrait.model_validate(wire)
    (source,) = labels.source
    assert isinstance(source, ngc.ReferenceObj)
    assert isinstance(source.path, ngc.DocPath) and source.path.href == "./raw"
    assert labels.model_dump(mode="json", exclude_none=True) == wire
    # instances pass through, including the convenience subclasses
    ref = ngc.ReferenceObj(type="multiscale", ref=mk(2), path=ngc.ZarrPath(href="./s1"))
    assert ngc.LabelsTrait(source=[ref]).source[0].path.href == "./s1"
    # the dataclass checks surface as pydantic validation errors
    with pytest.raises(ValidationError):
        ngc.LabelsTrait.model_validate(
            {
                **wire,
                "source": [
                    {
                        "type": "multiscale",
                        "ref": mk(2),
                        "path": {"type": "zarr", "format": "http", "href": "/local"},
                    }
                ],
            }
        )
    with pytest.raises(ValidationError):
        ngc.ScaleTransformation(input={"type": "coordinate_system", "ref": "not an id"})
