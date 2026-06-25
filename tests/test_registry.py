"""Node registry: family lookup, graceful fallback, and `register_family`.

This branch has three parallel node hierarchies, so a registration binds a family
of `node` / `ref` / `inlined` variants under one `type` key. The node factories
read the module-level `DEFAULT_REGISTRY`, so registering a type makes it parse
everywhere — including nested children — with no further wiring.
"""

from typing import Literal

import pytest
from pydantic import ValidationError

import ngio_collections as ngc


@pytest.fixture
def restore_registry():
    """Snapshot and restore `DEFAULT_REGISTRY` so test registrations don't leak."""
    saved = dict(ngc.DEFAULT_REGISTRY._types)
    yield ngc.DEFAULT_REGISTRY
    ngc.DEFAULT_REGISTRY._types.clear()
    ngc.DEFAULT_REGISTRY._types.update(saved)


# --- the mixin pattern: type + fields declared once, variants by inheritance ---


class TableType(ngc.NodeObj):
    # A custom type adds only the `type` literal; data lives in `attributes`.
    type: Literal["fractal:table"] = "fractal:table"


class TableNode(TableType, ngc.Node):
    pass


class RefTableNode(TableType, ngc.RefNode):
    pass


class InlinedTableNode(TableType, ngc.InlinedNode):
    pass


def _fresh() -> ngc.NodeRegistry:
    return ngc.NodeRegistry(ngc.Node, ngc.RefNode, ngc.InlinedNode)


# --- built-ins (now wired through register_family in _builtins) --------------


def test_default_registry_builtins():
    assert ngc.DEFAULT_REGISTRY.get_node("collection") is ngc.CollectionNode
    assert ngc.DEFAULT_REGISTRY.get_ref("multiscale") is ngc.RefMultiscaleNode
    assert ngc.DEFAULT_REGISTRY.get_inlined("collection") is ngc.InlinedCollectionNode
    assert ngc.DEFAULT_REGISTRY.get_ref("singlescale") is ngc.RefSinglescaleNode
    assert "collection" in ngc.DEFAULT_REGISTRY


def test_unregistered_type_falls_back_to_generic_bases():
    assert ngc.DEFAULT_REGISTRY.get_node("hcs-experiment") is ngc.Node
    assert ngc.DEFAULT_REGISTRY.get_ref("hcs-experiment") is ngc.RefNode
    assert ngc.DEFAULT_REGISTRY.get_inlined("hcs-experiment") is ngc.InlinedNode
    assert "hcs-experiment" not in ngc.DEFAULT_REGISTRY


def test_registered_but_partial_family_falls_back_per_variant():
    # `singlescale` ships with only a ref variant; the others fall back.
    assert ngc.DEFAULT_REGISTRY.get_ref("singlescale") is ngc.RefSinglescaleNode
    assert ngc.DEFAULT_REGISTRY.get_node("singlescale") is ngc.Node
    assert ngc.DEFAULT_REGISTRY.get_inlined("singlescale") is ngc.InlinedNode


# --- register_family ---------------------------------------------------------


def test_register_family_infers_slots_and_key():
    registry = _fresh()
    family = registry.register_family(TableNode, RefTableNode, InlinedTableNode)
    assert "fractal:table" in registry
    assert registry.get_node("fractal:table") is TableNode
    assert registry.get_ref("fractal:table") is RefTableNode
    assert registry.get_inlined("fractal:table") is InlinedTableNode
    assert family.node is TableNode and family.ref is RefTableNode


def test_register_family_ref_only():
    registry = _fresh()
    registry.register_family(RefTableNode)
    assert registry.get_ref("fractal:table") is RefTableNode
    assert registry.get_node("fractal:table") is ngc.Node  # falls back


def test_register_family_explicit_key_override():
    registry = _fresh()
    registry.register_family(TableNode, key="other")
    assert registry.get_node("other") is TableNode
    assert "fractal:table" not in registry


def test_nodes_forbid_node_level_extras():
    # A node's structural fields are a closed set: unknown top-level keys raise.
    with pytest.raises(ValidationError):
        ngc.Node(id="x", type="custom", surprise="nope")
    with pytest.raises(ValidationError):
        TableNode(id="x", surprise="nope")
    # Arbitrary / custom metadata still rides along in the open `attributes` dict.
    node = ngc.Node(id="x", type="custom", attributes={"x-demo:source": "fixture"})
    assert node.attributes["x-demo:source"] == "fixture"


def test_mixin_is_one_isinstance_target_across_variants():
    node = TableNode(id="t1")
    ref = RefTableNode(id="t1", path=ngc.JsonPath(path="./x.json"))
    inlined = InlinedTableNode(id="t1")
    assert isinstance(node, TableType)
    assert isinstance(ref, TableType)
    assert isinstance(inlined, TableType)


def test_register_family_rejects_bad_input():
    registry = _fresh()
    with pytest.raises(ValueError):
        registry.register_family()  # no variants
    with pytest.raises(ValueError):
        registry.register_family(TableNode, TableNode)  # two node-slot variants
    with pytest.raises(TypeError):
        registry.register_family(TableType)  # subclasses no node base
    with pytest.raises(ValueError):
        # variants disagree on the inferred key
        registry.register_family(TableNode, ngc.RefMultiscaleNode)


def test_registries_are_isolated_instances():
    a, b = _fresh(), _fresh()
    a.register_family(TableNode, RefTableNode, InlinedTableNode)
    assert "fractal:table" in a
    assert "fractal:table" not in b
    assert "fractal:table" not in ngc.DEFAULT_REGISTRY


# --- end-to-end through the default registry ---------------------------------


def test_registered_type_parses_via_default_registry(restore_registry):
    ngc.register_family(TableNode, RefTableNode, InlinedTableNode)

    root = ngc.CollectionNode(
        id="experiment",
        nodes=(
            TableNode(id="t1", attributes={"region": "FOV_1"}),
            ngc.Node(id="v1", type="mobie:view"),
        ),
    )
    reparsed = ngc.CollectionNode.model_validate(root.model_dump())
    table = reparsed.find(id="t1")
    view = reparsed.find(id="v1")
    assert type(table) is TableNode  # dispatched to the registered class
    assert table.attributes["region"] == "FOV_1"
    assert type(view) is ngc.Node  # unregistered: graceful degradation


def test_create_open_and_inline_roundtrip_custom_type(tmp_path, restore_registry):
    ngc.register_family(TableNode, RefTableNode, InlinedTableNode)
    resolver = ngc.Resolver(ngc.LocalStore())
    url = str(tmp_path / "collection.json")

    root = ngc.CollectionNode(
        id="experiment", nodes=(TableNode(id="t1", attributes={"region": "FOV_1"}),)
    )
    ngc.create(url, root, resolver, overwrite=True)

    table = ngc.open(url, resolver).find(id="t1")
    assert type(table) is TableNode
    assert table.attributes["region"] == "FOV_1"

    # t1 is embedded in the entry document, so its id stays bare.
    inlined = ngc.open_inlined(url, resolver).find(id="t1")
    assert type(inlined) is InlinedTableNode
    assert isinstance(inlined, TableType)
    assert inlined.attributes["region"] == "FOV_1"
