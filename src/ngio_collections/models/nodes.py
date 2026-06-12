"""Built-in node types: collection, multiscale, singlescale.

Child entries are parsed through the :class:`NodeRegistry` taken from the
Pydantic validation context (DESIGN.md §3.4), falling back to
``DEFAULT_REGISTRY``; unregistered types degrade to a plain ``BaseNode``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any, Literal

from pydantic import (
    PlainValidator,
    SerializeAsAny,
    ValidationInfo,
    model_validator,
)

from ngio_collections.models.base import BaseNode, PathObj


def validate_node(value: Any, *, context: dict[str, Any] | None = None) -> BaseNode:
    """Validate a node through the registry, falling back to ``BaseNode``.

    The registry comes from the validation context
    (``context={"registry": ...}``); without one, ``DEFAULT_REGISTRY`` is used.
    """
    # Imported lazily: the registry module imports this one at load time.
    from ngio_collections.registry import DEFAULT_REGISTRY

    registry = (context or {}).get("registry") or DEFAULT_REGISTRY

    if isinstance(value, dict):
        type_name = value.get("type")
        cls = registry.get(type_name) if isinstance(type_name, str) else BaseNode
        # Path-bearing dicts parse as the type's narrowed reference form, so
        # stub-ness is visible in the runtime type. A dict carrying both
        # `path` and `nodes` stays with the full class, whose XOR validator
        # reports the violation.
        if (
            cls.ref_form is not None
            and value.get("path") is not None
            and value.get("nodes") is None
        ):
            cls = cls.ref_form
        return cls.model_validate(value, context=context)
    if isinstance(value, BaseNode):
        cls = registry.get(value.type)
        if isinstance(value, cls):
            return value
        # Registered class is more specific than the instance: re-validate.
        return cls.model_validate(value.model_dump(by_alias=True), context=context)
    raise ValueError(f"cannot validate a node from value of type {type(value)!r}")


def _validate_node_field(value: Any, info: ValidationInfo) -> BaseNode:
    # The exact (value, info) signature matters: pydantic only passes the
    # validation context to validators it detects as info-taking.
    return validate_node(value, context=info.context)


# `PlainValidator` routes each child through the registry at validation time,
# so registrations are picked up without rebuilding a union. `SerializeAsAny`
# makes serialization use the runtime subclass (keeping e.g. `nodes`) rather
# than the declared `BaseNode` type.
Node = Annotated[
    SerializeAsAny[BaseNode],
    PlainValidator(_validate_node_field),
]


def _check_nodes_xor_path(node: BaseNode) -> None:
    nodes = getattr(node, "nodes", None)
    if (nodes is None) == (node.path is None):
        raise ValueError(
            f"{node.type!r} node {node.id!r}: exactly one of 'nodes' or 'path' "
            "must be set"
        )


def _check_child_names_unique(children: Sequence[BaseNode] | None) -> None:
    if not children:
        return
    seen: set[str] = set()
    for child in children:
        name = getattr(child, "name", None)
        if not isinstance(name, str):
            continue
        if name in seen:
            raise ValueError(f"duplicate child name {name!r} within the enclosing node")
        seen.add(name)


class CollectionNode(BaseNode):
    type: Literal["collection"] = "collection"
    nodes: list[Node] | None = None

    @model_validator(mode="after")
    def _check_structure(self) -> CollectionNode:
        _check_nodes_xor_path(self)
        _check_child_names_unique(self.nodes)
        return self


class SinglescaleNode(BaseNode):
    type: Literal["singlescale"] = "singlescale"

    @model_validator(mode="after")
    def _check_structure(self) -> SinglescaleNode:
        # A path-bearing singlescale may defer its transformations to the
        # document its `path` points to (see the RFC's externalized example).
        if self.path is None and "coordinateTransformations" not in self.attributes:
            raise ValueError(
                f"'singlescale' node {self.id!r}: 'coordinateTransformations' "
                "must be present in attributes when no 'path' is set"
            )
        return self


class MultiscaleNode(BaseNode):
    type: Literal["multiscale"] = "multiscale"
    nodes: list[SinglescaleNode] | None = None

    @model_validator(mode="after")
    def _check_structure(self) -> MultiscaleNode:
        _check_nodes_xor_path(self)
        _check_child_names_unique(self.nodes)
        # Path-stub multiscales (see the RFC's tiles example) carry no
        # attributes; the MUST applies to the full, inlined form only.
        if self.nodes is not None and "coordinateSystems" not in self.attributes:
            raise ValueError(
                f"'multiscale' node {self.id!r}: 'coordinateSystems' must be "
                "present in attributes when 'nodes' is set"
            )
        return self


# Reference forms: the same on-the-wire node (the spec has one `type` for
# both), narrowed so stub-ness shows in the Python type — `path` required,
# `nodes` forbidden. Parsed path-bearing dicts and the sync writers' return
# values carry these; isinstance against the full class still holds (a
# reference IS a collection/multiscale, in stub form). Singlescale has no
# reference form: its `path` doubles as the data pointer of the inlined form.


class CollectionRef(CollectionNode):
    """Reference form of a collection: points at an external document."""

    nodes: None = None
    path: PathObj


class MultiscaleRef(MultiscaleNode):
    """Reference form of a multiscale: points at an external document."""

    nodes: None = None
    path: PathObj


CollectionNode.ref_form = CollectionRef
MultiscaleNode.ref_form = MultiscaleRef
