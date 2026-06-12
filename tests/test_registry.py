"""Node registry: register / lookup / fallback, and instance isolation."""

import pytest

import ome_zarr_collections as ozc


def test_default_registry_builtins():
    assert ozc.DEFAULT_REGISTRY.get("collection") is ozc.CollectionNode
    assert ozc.DEFAULT_REGISTRY.get("multiscale") is ozc.MultiscaleNode
    assert ozc.DEFAULT_REGISTRY.get("singlescale") is ozc.SinglescaleNode


def test_unregistered_type_falls_back_to_base_node():
    assert ozc.DEFAULT_REGISTRY.get("hcs-experiment") is ozc.BaseNode
    assert "hcs-experiment" not in ozc.DEFAULT_REGISTRY


def test_register_custom_node_type():
    class CustomNode(ozc.BaseNode):
        pass

    registry = ozc.NodeRegistry()
    registry.register("custom", CustomNode)
    assert "custom" in registry
    assert registry.get("custom") is CustomNode


def test_registries_are_isolated_instances():
    class CustomNode(ozc.BaseNode):
        pass

    a = ozc.NodeRegistry()
    b = ozc.NodeRegistry()
    a.register("custom", CustomNode)
    assert "custom" in a
    assert "custom" not in b
    assert "custom" not in ozc.DEFAULT_REGISTRY


def test_node_registry_rejects_bad_registrations():
    registry = ozc.NodeRegistry()
    with pytest.raises(ValueError):
        registry.register("", ozc.CollectionNode)
    with pytest.raises(TypeError):
        registry.register("dict", dict)
