"""Shared base for the pydantic value models (the optional `validate` tier).

`BaseObj` is the frozen Pydantic base for non-node OME value objects (traits,
declarations, transformations). RFC-8 revision 1 writes snake_case keys
(`coordinate_systems`, `row_index`, …), so models serialize by field name; a
camelCase spelling is still accepted on read so older documents can be
inspected. `UuidStr` is the constrained id field those models use. This module
imports pydantic at import time; the core never imports it.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AliasChoices, AliasGenerator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ngio_collections.models._ids import UUID_PATTERN

UuidStr = Annotated[str, Field(pattern=UUID_PATTERN)]
"""A pydantic string field constrained to the canonical UUID form."""


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
