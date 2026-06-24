"""Pure model layer: frozen nodes, paths, references, and the edit engine.

This subpackage re-exports the model types that make up the public API. The node
constructors and `_document` plumbing stay internal to
``ngio_collections.models._base``; the built-in node families live in their own
``_collection`` / ``_multiscale`` / ``_singlescale`` modules and are wired into
``DEFAULT_REGISTRY`` here via ``register_builtins``.
"""

from ngio_collections.models._base import (
    DEFAULT_REGISTRY,
    AnyInlinedNode,
    AnyNode,
    BaseNode,
    IdStr,
    InlinedNode,
    JsonPath,
    Node,
    NodeObj,
    NodeState,
    NodeStateError,
    PathObj,
    RefNode,
    ReferenceObj,
    ZarrPath,
    register_family,
)
from ngio_collections.models._builtins import register_builtins
from ngio_collections.models._collection import (
    CollectionNode,
    CollectionType,
    InlinedCollectionNode,
    RefCollectionNode,
)
from ngio_collections.models._multiscale import (
    InlinedMultiscaleNode,
    MultiscaleNode,
    MultiscaleType,
    RefMultiscaleNode,
)
from ngio_collections.models._registry import NodeRegistry, NodeTypes
from ngio_collections.models._singlescale import (
    RefSinglescaleNode,
    SinglescaleType,
)

register_builtins()

__all__ = [
    "DEFAULT_REGISTRY",
    "AnyInlinedNode",
    "AnyNode",
    "BaseNode",
    "CollectionNode",
    "CollectionType",
    "IdStr",
    "InlinedCollectionNode",
    "InlinedMultiscaleNode",
    "InlinedNode",
    "JsonPath",
    "MultiscaleNode",
    "MultiscaleType",
    "Node",
    "NodeObj",
    "NodeRegistry",
    "NodeState",
    "NodeStateError",
    "NodeTypes",
    "PathObj",
    "RefCollectionNode",
    "RefMultiscaleNode",
    "RefNode",
    "RefSinglescaleNode",
    "ReferenceObj",
    "SinglescaleType",
    "ZarrPath",
    "register_family",
]
