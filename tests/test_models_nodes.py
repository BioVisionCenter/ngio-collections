"""Node structural validators and registry-driven child parsing."""

from typing import Literal

import pytest
from pydantic import ValidationError

import ngio_collections as ngc
from ngio_collections.models import validate_node

COORD_SYSTEMS = [{"id": "physical", "axes": [{"name": "x", "type": "space"}]}]
SCALE_TRANSFORMS = [
    {
        "type": "scale",
        "scale": [1.0],
        "input": {"id": "s0"},
        "output": {"id": "physical"},
    }
]


def _singlescale_stub() -> ngc.SinglescaleNode:
    return ngc.SinglescaleNode(id="s0", name="s0", path=ngc.ZarrPath(path="./s0"))


def test_collection_requires_nodes_xor_path():
    with pytest.raises(ValidationError, match="exactly one"):
        ngc.CollectionNode(id="c", name="c")
    with pytest.raises(ValidationError, match="exactly one"):
        ngc.CollectionNode(id="c", name="c", nodes=[], path=ngc.ZarrPath(path="./x"))
    assert ngc.CollectionNode(id="c", name="c", nodes=[]).nodes == []
    assert (
        ngc.CollectionNode(id="c", name="c", path=ngc.ZarrPath(path="./x")).nodes
        is None
    )


def test_child_names_unique_within_collection():
    child_a = ngc.BaseNode(type="x", id="a", name="same")
    child_b = ngc.BaseNode(type="x", id="b", name="same")
    with pytest.raises(ValidationError, match="duplicate child name"):
        ngc.CollectionNode(id="c", name="c", nodes=[child_a, child_b])


def test_multiscale_inline_requires_coordinate_systems():
    with pytest.raises(ValidationError, match="coordinateSystems"):
        ngc.MultiscaleNode(id="m", name="m", nodes=[_singlescale_stub()])
    node = ngc.MultiscaleNode(
        id="m",
        name="m",
        nodes=[_singlescale_stub()],
        attributes={"coordinateSystems": COORD_SYSTEMS},
    )
    assert node.nodes is not None
    # A path stub carries no attributes (RFC tiles example).
    stub = ngc.MultiscaleNode(id="m2", name="m2", path=ngc.ZarrPath(path="./m2.zarr"))
    assert stub.attributes == {}


def test_multiscale_requires_nodes_xor_path():
    with pytest.raises(ValidationError, match="exactly one"):
        ngc.MultiscaleNode(
            id="m", name="m", attributes={"coordinateSystems": COORD_SYSTEMS}
        )


def test_singlescale_requires_transformations_when_inline():
    with pytest.raises(ValidationError, match="coordinateTransformations"):
        ngc.SinglescaleNode(id="s0", name="s0")
    inline = ngc.SinglescaleNode(
        id="s0",
        name="s0",
        attributes={"coordinateTransformations": SCALE_TRANSFORMS},
    )
    assert inline.path is None
    # With a path the transformations may live in the referenced document.
    assert _singlescale_stub().attributes == {}


def test_unknown_type_is_opaque_and_round_trips_extras():
    node = validate_node(
        {"type": "mobie:table", "id": "t1", "name": "table", "customField": 42}
    )
    assert type(node) is ngc.BaseNode
    assert node.model_dump(by_alias=True)["customField"] == 42


def test_children_parse_through_default_registry():
    collection = ngc.CollectionNode.model_validate(
        {
            "type": "collection",
            "id": "c",
            "name": "c",
            "nodes": [
                {
                    "type": "multiscale",
                    "id": "m",
                    "name": "m",
                    "path": {"type": "zarr", "path": "./m.zarr"},
                },
                {"type": "custom:thing", "id": "x", "name": "x"},
            ],
        }
    )
    assert isinstance(collection.nodes[0], ngc.MultiscaleNode)
    # Unregistered types degrade to the opaque BaseNode.
    assert type(collection.nodes[1]) is ngc.BaseNode


def test_registry_from_validation_context():
    class FractalRoiNode(ngc.BaseNode):
        type: Literal["fractal:roi"] = "fractal:roi"

    registry = ngc.NodeRegistry()
    registry.register("collection", ngc.CollectionNode)
    registry.register("fractal:roi", FractalRoiNode)

    data = {
        "type": "collection",
        "id": "c",
        "name": "c",
        "nodes": [{"type": "fractal:roi", "id": "r1", "name": "roi"}],
    }
    with_context = ngc.CollectionNode.model_validate(
        data, context={"registry": registry}
    )
    assert isinstance(with_context.nodes[0], FractalRoiNode)

    # Without the context, the custom type is unknown to DEFAULT_REGISTRY.
    without_context = ngc.CollectionNode.model_validate(data)
    assert type(without_context.nodes[0]) is ngc.BaseNode


def test_context_registry_threads_through_nested_documents():
    class FractalRoiNode(ngc.BaseNode):
        type: Literal["fractal:roi"] = "fractal:roi"

    registry = ngc.NodeRegistry()
    registry.register("collection", ngc.CollectionNode)
    registry.register("fractal:roi", FractalRoiNode)

    data = {
        "type": "collection",
        "id": "outer",
        "name": "outer",
        "nodes": [
            {
                "type": "collection",
                "id": "inner",
                "name": "inner",
                "nodes": [{"type": "fractal:roi", "id": "r1", "name": "roi"}],
            }
        ],
    }
    parsed = ngc.CollectionNode.model_validate(data, context={"registry": registry})
    inner = parsed.nodes[0]
    assert isinstance(inner, ngc.CollectionNode)
    assert isinstance(inner.nodes[0], FractalRoiNode)


def test_validate_node_rejects_non_node_values():
    with pytest.raises(ValueError, match="cannot validate"):
        validate_node(42)


def _nested_collection() -> ngc.CollectionNode:
    return ngc.CollectionNode.model_validate(
        {
            "type": "collection",
            "id": "root",
            "name": "root",
            "nodes": [
                {
                    "type": "collection",
                    "id": "inner",
                    "name": "inner",
                    "nodes": [{"type": "custom:thing", "id": "x", "name": "x"}],
                },
                {
                    "type": "multiscale",
                    "id": "m",
                    "name": "m",
                    "path": {"type": "zarr", "path": "./m.zarr"},
                },
            ],
        }
    )


def test_walk_yields_self_then_descendants_in_document_order():
    collection = _nested_collection()
    assert [node.id for node in collection.walk()] == ["root", "inner", "x", "m"]


def test_walk_on_leaf_yields_only_itself():
    leaf = _singlescale_stub()
    assert list(leaf.walk()) == [leaf]


def test_walk_yields_stubs_without_descending():
    collection = _nested_collection()
    stub = next(node for node in collection.walk() if node.id == "m")
    assert isinstance(stub, ngc.MultiscaleRef)
    assert list(stub.walk()) == [stub]


def test_find_returns_descendant_self_or_none():
    collection = _nested_collection()
    deep = collection.find("x")
    assert deep is not None and deep.id == "x"
    assert collection.find("root") is collection
    assert collection.find("missing") is None


def test_find_is_scoped_to_the_subtree():
    collection = _nested_collection()
    inner = collection.nodes[0]
    assert inner.find("x") is not None
    assert inner.find("m") is None
    assert inner.find("root") is None
