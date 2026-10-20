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


def test_scene_trait_accepts_camel_case_and_writes_snake_case() -> None:
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
    assert set(dumped) == {"type", "coordinate_systems", "coordinate_transformations"}
    assert "coordinateSystems" not in dumped


def test_reference_obj_is_typed_uuid_and_closed() -> None:
    ref = ngc.ReferenceObj(type="scale", ref=mk(0xC))
    assert ref.to_dict() == {
        "type": "scale",
        "ref": mk(0xC),
    }
    with pytest.raises(ValueError):
        ngc.ReferenceObj(type="scale", ref="s0")  # not a UUID
    with pytest.raises(ValueError):
        ngc.ReferenceObj.from_dict({"type": "scale", "ref": mk(1), "name": "x"})
    with pytest.raises(ValueError):
        ngc.ReferenceObj.from_dict({"type": "scale", "id": mk(1)})  # a declaration
    with_path = ngc.ReferenceObj.from_dict(
        {
            "type": "coordinate_system",
            "ref": mk(0x20),
            "path": {"type": "zarr", "format": "relative", "href": "./raw"},
        }
    )
    assert with_path.path is not None and with_path.path.href == "./raw"


def test_multiscale_fields_validate_the_revision_example() -> None:
    raw = json.loads((FIXTURES / "collection" / "raw" / "zarr.json").read_text())
    ome = raw["attributes"]["ome"]
    fields = ngc.MultiscaleFields.model_validate(
        {k: v for k, v in ome.items() if k in ("coordinate_systems", "scales")}
    )
    (system,) = fields.coordinate_systems
    assert system.type == "coordinate_system" and system.id == mk(0x20)
    assert [a.name for a in system.axes] == ["c", "z", "y", "x"]
    s0, s1 = fields.scales
    assert s0.type == "scale" and s0.path.href == "./s0"
    (tf,) = s1.coordinate_transformations
    assert isinstance(tf, ngc.ScaleTransformation) and tf.scale == [1, 0.5, 0.2, 0.2]
    assert tf.input is not None and tf.input.type == "scale" and tf.input.ref == s1.id
    assert tf.output is not None and tf.output.ref == mk(0x20)


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
    assert ngc.is_uuid(fresh) and fresh[14] == "7"  # UUIDv7
    assert ngc.new_id() != fresh
    assert ngc.is_uuid(mk(1)) and not ngc.is_uuid("img") and not ngc.is_uuid(None)


def test_extension_manifest_registry_and_derivation() -> None:
    napari = ngc.ExtensionManifestEntry(
        id="https://napari.org/ngff/",
        version="1.0",
        schemas=[
            ngc.SchemaRef(
                type="json_schema", url="https://napari.org/ngff/1.0/schema.json"
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


def test_dataclass_locators_work_as_pydantic_fields() -> None:
    """`DocPath` / `ReferenceObj` are stdlib dataclasses; pydantic coerces them."""
    wire = {
        "type": "scale",
        "id": mk(0x30),
        "path": {"type": "zarr", "format": "relative", "href": "./s0"},
        "coordinate_transformations": [
            {
                "type": "scale",
                "scale": [1.0, 2.0],
                "input": {"type": "scale", "ref": mk(0x30)},
                "output": {"type": "coordinate_system", "ref": mk(0x20)},
            }
        ],
    }
    scale = ngc.Scale.model_validate(wire)
    assert isinstance(scale.path, ngc.DocPath) and scale.path.href == "./s0"
    (transform,) = scale.coordinate_transformations
    assert isinstance(transform.input, ngc.ReferenceObj)
    assert transform.input.path is None
    assert scale.model_dump(mode="json", exclude_none=True) == wire
    # instances pass through, including the convenience subclasses
    assert ngc.Scale(id=mk(0x30), path=ngc.ZarrPath(href="./s1")).path.href == "./s1"
    # the dataclass checks surface as pydantic validation errors
    with pytest.raises(ValidationError):
        ngc.Scale.model_validate(
            {**wire, "path": {"type": "zarr", "format": "http", "href": "/local"}}
        )
    with pytest.raises(ValidationError):
        ngc.ReferenceObj  # noqa: B018  (still importable)
        ngc.ScaleTransformation(input={"type": "scale", "ref": "not-a-uuid"})
