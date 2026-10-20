"""Shared base for the OME value models.

`BaseObj` is the frozen Pydantic base for non-node OME value objects (paths,
references, traits, declarations). RFC-8 revision 1 writes snake_case keys
(`coordinate_systems`, `row_index`, …), so models serialize by field name; a
camelCase spelling is still accepted on read so older documents can be
inspected. `NodeStateError` flags a node that is in the wrong state for a
requested operation. Pure data layer: no IO.
"""

from __future__ import annotations

from pydantic import AliasChoices, AliasGenerator, BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


def _read_aliases(field_name: str) -> AliasChoices:
    """Accept both the snake_case field name and its camelCase spelling."""
    return AliasChoices(field_name, to_camel(field_name))


class BaseObj(BaseModel):
    """Frozen base for OME value objects: snake_case out, snake or camel in.

    `extra="allow"` round-trips unknown / custom keys.
    """

    model_config = ConfigDict(
        alias_generator=AliasGenerator(validation_alias=_read_aliases),
        populate_by_name=True,
        extra="allow",
        frozen=True,
    )


class NodeStateError(ValueError):
    """A node is in the wrong state for the requested operation.

    Subclasses `ValueError` so callers can keep catching `ValueError`. The
    message points to the API that fits the node's actual state.
    """
