"""Shared base for the OME value models.

`BaseObj` is the frozen, camelCase-aliased Pydantic base for non-node OME value
objects (paths, references, attributes). `NodeStateError` flags a node that is in
the wrong state for a requested operation. Pure data layer: no IO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class BaseObj(BaseModel):
    """Frozen, camelCase-aliased base for OME value objects (paths, refs, attrs).

    `extra="allow"` round-trips unknown / custom keys.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
        frozen=True,
    )


class NodeStateError(ValueError):
    """A node is in the wrong state for the requested operation.

    Subclasses `ValueError` so callers can keep catching `ValueError`. The
    message points to the API that fits the node's actual state.
    """
