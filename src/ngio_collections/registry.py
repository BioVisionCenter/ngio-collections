"""Node registry.

Registries are plain objects, not singletons (DESIGN.md §3.4): tests and
third-party packages can build their own, and two configurations (e.g. two
spec versions) can coexist in one process. The module-level default keeps
everyday ergonomics. Parsing reads the registry from Pydantic's validation
context (``model_validate(..., context={"registry": ...})``), falling back to
``DEFAULT_REGISTRY``.
"""

from __future__ import annotations

from ngio_collections.models.base import BaseNode
from ngio_collections.models.nodes import (
    CollectionNode,
    MultiscaleNode,
    SinglescaleNode,
)


class NodeRegistry:
    """Maps a node ``type`` key to its model class.

    Unregistered types fall back to the generic :class:`BaseNode`, per the
    RFC's graceful-degradation rules.
    """

    def __init__(self) -> None:
        self._types: dict[str, type[BaseNode]] = {}

    def register(self, key: str, node_cls: type[BaseNode]) -> None:
        """Register ``node_cls`` under the explicit type ``key``."""
        if not key:
            raise ValueError("registration key must be a non-empty string")
        if not (isinstance(node_cls, type) and issubclass(node_cls, BaseNode)):
            raise TypeError(f"{node_cls!r} is not a BaseNode subclass")
        self._types[key] = node_cls

    def get(self, key: str) -> type[BaseNode]:
        """The model class for ``key``; ``BaseNode`` if unregistered."""
        return self._types.get(key, BaseNode)

    def __contains__(self, key: str) -> bool:
        return key in self._types


def _default_node_registry() -> NodeRegistry:
    registry = NodeRegistry()
    registry.register("collection", CollectionNode)
    registry.register("multiscale", MultiscaleNode)
    registry.register("singlescale", SinglescaleNode)
    return registry


DEFAULT_REGISTRY = _default_node_registry()
