"""Shared Pydantic config bases and node-state types.

Pure data layer: no IO and no dependency on the node models. `BaseObj` and
`NodeObj` are the two frozen, camelCase-aliased model bases the rest of the
package builds on — they differ only in their `extra` policy. `NodeState` /
`NodeStateError` describe how a node relates to on-disk storage.
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


class NodeObj(BaseModel):
    """Frozen, camelCase-aliased base for the node hierarchy and node mixins.

    Identical to `BaseObj` except `extra="forbid"`: a node's structural fields
    are a closed set, so unknown node-level keys are rejected rather than
    silently kept. Arbitrary / custom metadata belongs in a node's `attributes`
    dict (which stays open). Consumers declaring a custom node type build their
    field mixin on this base so the derived variants stay strict.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class NodeStateError(ValueError):
    """A node is in the wrong state for the requested operation.

    Subclasses `ValueError` so callers can keep catching `ValueError`. The
    message points to the API that fits the node's actual state.
    """


class NodeState(StrEnum):
    """How a node relates to on-disk storage (see :attr:`BaseNode.state`)."""

    DETACHED = "detached"  # in memory only, no backing document
    DOCUMENT = "document"  # backed by a document (root or descendant)
