"""Node registry: register / lookup / fallback, and instance isolation."""

import pytest

import ngio_collections as ngc


def test_default_registry_builtins():
    assert ngc.DEFAULT_REGISTRY.get("collection") is ngc.CollectionNode
    assert ngc.DEFAULT_REGISTRY.get("multiscale") is ngc.MultiscaleNode
    assert ngc.DEFAULT_REGISTRY.get("singlescale") is ngc.SinglescaleNode


def test_unregistered_type_falls_back_to_base_node():
    assert ngc.DEFAULT_REGISTRY.get("hcs-experiment") is ngc.BaseNode
    assert "hcs-experiment" not in ngc.DEFAULT_REGISTRY


def test_register_custom_node_type():
    class CustomNode(ngc.BaseNode):
        pass

    registry = ngc.NodeRegistry()
    registry.register("custom", CustomNode)
    assert "custom" in registry
    assert registry.get("custom") is CustomNode


def test_registries_are_isolated_instances():
    class CustomNode(ngc.BaseNode):
        pass

    a = ngc.NodeRegistry()
    b = ngc.NodeRegistry()
    a.register("custom", CustomNode)
    assert "custom" in a
    assert "custom" not in b
    assert "custom" not in ngc.DEFAULT_REGISTRY


def test_node_registry_rejects_bad_registrations():
    registry = ngc.NodeRegistry()
    with pytest.raises(ValueError):
        registry.register("", ngc.CollectionNode)
    with pytest.raises(TypeError):
        registry.register("dict", dict)
