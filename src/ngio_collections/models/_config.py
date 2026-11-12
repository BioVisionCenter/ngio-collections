"""Shared base for the pydantic value models (the optional `validate` tier).

`BaseObj` is the frozen Pydantic base for non-node OME value objects (traits,
declarations, transformations). Models serialize by field name unless a field
declares a wire key with `wire(...)`: RFC-8 revision 2 spells some keys in
camelCase (`coordinateSystems`, `coordinateTransformations`) and the Python
attributes stay snake_case. On read, a field without a declared wire key accepts
its snake_case name and the camelCase spelling of it. `IdStr` is the constrained
id field those models use. This module imports pydantic at import time; the core
never imports it.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import AliasChoices, AliasGenerator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ngio_collections.models._ids import ID_PATTERN

IdStr = Annotated[str, Field(pattern=ID_PATTERN)]
"""A pydantic string field constrained to a valid id (`ID_PATTERN`)."""


def _read_aliases(field_name: str) -> AliasChoices:
    """Accept both the snake_case field name and its camelCase spelling."""
    return AliasChoices(field_name, to_camel(field_name))


def wire(key: str, **kwargs: Any) -> Any:
    """Return a pydantic field written and read under the wire key `key`.

    The attribute keeps its Python name (still accepted by the constructor);
    `kwargs` are passed on to `Field`.
    """
    return Field(validation_alias=key, serialization_alias=key, **kwargs)


class BaseObj(BaseModel):
    """Frozen base for OME value objects, dumped under their wire keys.

    `extra="allow"` round-trips unknown / custom keys.
    """

    model_config = ConfigDict(
        alias_generator=AliasGenerator(validation_alias=_read_aliases),
        populate_by_name=True,
        extra="allow",
        frozen=True,
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Dump the model, by wire key unless `by_alias=False` is passed."""
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)

    def model_dump_json(self, **kwargs: Any) -> str:
        """Dump the model as JSON, by wire key unless `by_alias=False` is passed."""
        kwargs.setdefault("by_alias", True)
        return super().model_dump_json(**kwargs)
