"""Shared bases and node-state types.

Pure data layer: no IO and no dependency on the node models. `BaseObj` is the
frozen, camelCase-aliased *Pydantic* base for non-node OME value objects (paths,
references, attributes). `NodeObj` is a plain (non-Pydantic) marker base for the
node hierarchy — the node spine is hand-rolled for performance (see `_nodes`), so
`NodeObj` carries no fields or validation, only the shared identity that lets
`isinstance(node, NodeObj)` hold and custom families declare their type marker.
`NodeState` / `NodeStateError` describe how a node relates to on-disk storage.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class BaseObj(BaseModel):
    """Frozen, camelCase-aliased base for non-node OME objects (paths, refs).

    `extra="allow"` round-trips unknown / custom keys. Nodes do *not* use this
    base — see `NodeObj`.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
        frozen=True,
    )


class NodeObj:
    """Plain marker base for the node hierarchy and node type-markers.

    The node spine (`BaseNode` and subtypes in `_nodes`) is a hand-rolled frozen
    `__slots__` hierarchy rather than Pydantic — node fields are a closed, trivial
    schema and per-node Pydantic construction dominated read cost (see
    `benchmarks/README.md`). `NodeObj` stays as the shared marker so every node is
    an `isinstance(_, NodeObj)`, and a custom family declares its type once::

        class TableType(NodeObj):
            __slots__ = ()
            node_type = "fractal:table"

    `extra="forbid"` (rejecting unknown node-level keys) is enforced by the node
    constructors in `_nodes`, not here. Arbitrary metadata still rides in a node's
    open `attributes` dict.
    """

    __slots__ = ()


class NodeStateError(ValueError):
    """A node is in the wrong state for the requested operation.

    Subclasses `ValueError` so callers can keep catching `ValueError`. The
    message points to the API that fits the node's actual state.
    """


class NodeState(StrEnum):
    """How a node relates to on-disk storage (see :attr:`BaseNode.state`)."""

    DETACHED = "detached"  # in memory only, no backing document
    DOCUMENT = "document"  # backed by a document (root or descendant)
