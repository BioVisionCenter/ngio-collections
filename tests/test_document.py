"""MetadataDocument layer: envelope detection, provenance, the single serialize
path, stub emission, and round-trip fidelity (ROADMAP M2)."""

import json

import pytest

import ome_zarr_collections as ozc
from ome_zarr_collections.document import DEFAULT_VERSION

# RFC-8: "A multiscale group with a single, inlined resolution level"
# (axes concretized; the RFC uses "..." placeholders).
INLINE_MULTISCALE = {
    "ome": {
        "version": "0.x",
        "type": "multiscale",
        "name": "multiscales_example",
        "id": "image_0",
        "nodes": [
            {
                "id": "s0",
                "name": "s0",
                "type": "singlescale",
                "path": {"type": "zarr", "path": "./s0"},
                "attributes": {
                    "coordinateTransformations": [
                        {
                            "type": "scale",
                            "scale": [1, 1, 1],
                            "input": {"id": "s0"},
                            "output": {"id": "physical"},
                        }
                    ]
                },
            }
        ],
        "attributes": {
            "coordinateSystems": [
                {"id": "physical", "axes": [{"name": "x", "type": "space"}]}
            ]
        },
    }
}

# RFC-8: tiles collection with a `scene` attribute (abridged).
TILES = {
    "ome": {
        "version": "0.x",
        "type": "collection",
        "name": "Tiles",
        "id": "tiles",
        "attributes": {
            "scene": {
                "coordinateSystems": [
                    {"id": "world", "axes": [{"name": "x", "type": "space"}]}
                ],
                "coordinateTransformations": [
                    {
                        "type": "translation",
                        "translation": [0, 0, 100],
                        "input": {
                            "path": {"type": "zarr", "path": "./tile_0.zarr"},
                            "id": "physical",
                        },
                        "output": {"id": "world"},
                    }
                ],
            }
        },
        "nodes": [
            {
                "type": "multiscale",
                "id": "tile_0",
                "name": "Tile 0",
                "path": {"type": "zarr", "path": "./tile_0.zarr"},
            },
            {
                "type": "multiscale",
                "id": "tile_1",
                "name": "Tile 1",
                "path": {"type": "zarr", "path": "./tile_1.zarr"},
            },
        ],
    }
}

URL = "/data/collection.json"


def test_parse_inline_multiscale():
    doc = ozc.parse_metadata_document(INLINE_MULTISCALE, url=URL)
    assert doc.form == "json"
    assert doc.url == URL
    assert doc.version == "0.x"
    assert isinstance(doc.root, ozc.MultiscaleNode)
    assert isinstance(doc.root.nodes[0], ozc.SinglescaleNode)
    # The version lives on the MetadataDocument, not on the root node.
    assert "version" not in doc.root.model_dump(by_alias=True)


def test_round_trip_inline_multiscale():
    doc = ozc.parse_metadata_document(INLINE_MULTISCALE, url=URL)
    assert doc.serialize() == INLINE_MULTISCALE


def test_round_trip_tiles_with_scene():
    doc = ozc.parse_metadata_document(TILES, url=URL)
    assert isinstance(doc.root, ozc.CollectionNode)
    scene = doc.root.attrs[ozc.SceneAttribute]
    assert scene.coordinate_transformations[0].output.id == "world"
    assert doc.serialize() == TILES


def test_zarr_form_detection_and_serialization():
    zarr_doc = {
        "zarr_format": 3,
        "node_type": "group",
        "attributes": {"ome": INLINE_MULTISCALE["ome"]},
    }
    doc = ozc.parse_metadata_document(zarr_doc, url="/data/image.zarr/zarr.json")
    assert doc.form == "zarr"
    assert doc.serialize() == zarr_doc


def test_serialize_bytes_round_trips():
    doc = ozc.parse_metadata_document(INLINE_MULTISCALE, url=URL)
    reparsed = ozc.parse_metadata_document(doc.serialize_bytes(), url=URL)
    assert reparsed.serialize_bytes() == doc.serialize_bytes()


def test_default_version_injected():
    payload = {"ome": {"type": "collection", "id": "c", "name": "c", "nodes": []}}
    doc = ozc.parse_metadata_document(payload, url=URL)
    assert doc.version == DEFAULT_VERSION
    assert doc.serialize()["ome"]["version"] == DEFAULT_VERSION


def test_missing_ome_key_rejected():
    with pytest.raises(ValueError, match="ome"):
        ozc.parse_metadata_document(
            {"type": "collection", "id": "c", "name": "c", "nodes": []}, url=URL
        )


def test_duplicate_ids_within_document_rejected():
    payload = {
        "ome": {
            "version": "0.x",
            "type": "collection",
            "id": "c",
            "name": "c",
            "nodes": [
                {
                    "type": "multiscale",
                    "id": "dup",
                    "name": "a",
                    "path": {"type": "zarr", "path": "./a.zarr"},
                },
                {
                    "type": "multiscale",
                    "id": "dup",
                    "name": "b",
                    "path": {"type": "zarr", "path": "./b.zarr"},
                },
            ],
        }
    }
    with pytest.raises(ValueError, match="duplicate node id"):
        ozc.parse_metadata_document(payload, url=URL)


def test_parse_uses_registry_argument():
    registry = ozc.NodeRegistry()  # empty: nothing registered
    doc = ozc.parse_metadata_document(TILES, url=URL, registry=registry)
    assert type(doc.root) is ozc.BaseNode


def test_provenance_back_references():
    doc = ozc.parse_metadata_document(INLINE_MULTISCALE, url=URL)
    assert doc.root._document is doc
    assert doc.root._parent is None
    child = doc.root.nodes[0]
    assert child._document is doc
    assert child._parent is doc.root


def test_copies_and_revalidation_are_detached():
    doc = ozc.parse_metadata_document(INLINE_MULTISCALE, url=URL)
    copied = doc.root.model_copy()
    assert copied._document is None
    revalidated = ozc.MultiscaleNode.model_validate(doc.root.model_dump(by_alias=True))
    assert revalidated._document is None


def test_externalized_child_emitted_as_stub():
    parent = ozc.parse_metadata_document(
        {
            "ome": {
                "version": "0.x",
                "type": "collection",
                "id": "root",
                "name": "root",
                "nodes": [
                    {
                        "type": "collection",
                        "id": "child",
                        "name": "child",
                        "path": {"type": "json", "path": "./child/collection.json"},
                    }
                ],
            }
        },
        url="/data/collection.json",
    )
    child = ozc.parse_metadata_document(
        {
            "ome": {
                "version": "0.x",
                "type": "collection",
                "id": "child",
                "name": "child",
                "nodes": [],
            }
        },
        url="/data/child/collection.json",
        stub_path=ozc.JsonPath(path="./child/collection.json"),
    )
    original = parent.serialize()
    # Graft the resolved child over its stub, as the resolver's children()
    # never would (non-mutating resolution) but a user explicitly might.
    parent.root.nodes[0] = child.root
    assert parent.serialize() == original


def test_stub_emission_without_stub_path_rejected():
    parent = ozc.parse_metadata_document(
        {
            "ome": {
                "version": "0.x",
                "type": "collection",
                "id": "p",
                "name": "p",
                "nodes": [],
            }
        },
        url="/data/collection.json",
    )
    orphan = ozc.parse_metadata_document(
        {
            "ome": {
                "version": "0.x",
                "type": "collection",
                "id": "o",
                "name": "o",
                "nodes": [],
            }
        },
        url="/data/other.json",  # no stub_path
    )
    parent.root.nodes.append(orphan.root)
    with pytest.raises(ValueError, match="stub_path"):
        parent.serialize()


def _ome_payload(path):
    data = json.loads(path.read_text())
    return data["attributes"]["ome"] if path.name == "zarr.json" else data["ome"]


def test_fixture_round_trip(reference):
    """parse → serialize is stable (modulo key ordering) on every fixture
    document, in both envelope forms."""
    _, directory = reference
    for path in sorted(directory.rglob("*.json")):
        raw = json.loads(path.read_text())
        doc = ozc.parse_metadata_document(path.read_bytes(), url=str(path))
        serialized = doc.serialize()
        if doc.form == "json":
            assert serialized == raw, path
        else:
            # Sibling keys of zarr.json (e.g. custom_key) are preserved by
            # Resolver.save's read-modify-write, not by serialize().
            assert serialized["attributes"]["ome"] == raw["attributes"]["ome"], path
        # Second generation is byte-stable.
        reparsed = ozc.parse_metadata_document(doc.serialize_bytes(), url=str(path))
        assert reparsed.serialize_bytes() == doc.serialize_bytes(), path


def test_fixture_fidelity_unknown_attributes_and_prefixed_fields():
    from pathlib import Path

    path = (
        Path(__file__).parent
        / "data"
        / "mixed"
        / "externalised_child"
        / "collection.json"
    )
    doc = ozc.parse_metadata_document(path.read_bytes(), url=str(path))
    serialized = doc.serialize()["ome"]
    # Unknown attribute and custom-prefixed field survive untouched.
    assert serialized["attributes"]["x-demo:note"] == "externalised child document"
    assert serialized["x-demo:source"] == "fixture"
