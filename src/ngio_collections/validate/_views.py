"""Trait lenses: read a node's traits and fields through typed models.

A node carries its semantic roles as entries in its `traits` (indexed by trait
`type`); each trait model fixes the `type` it maps to. These helpers turn a raw
entry into the validated model on demand, operating on a `NodeRecord`. They are
*composable*: a node carrying both `well` and `scene` answers `has_trait` for
each, independently. `read_fields` does the same for node-type fields
(`MultiscaleFields`).

This module imports no pydantic: it only calls `trait_type()` / `model_validate`
on the model *classes* the caller hands it, and those classes cannot exist
without the `validate` extra installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from ngio_collections.graph import NodeRecord

if TYPE_CHECKING:
    from ngio_collections.models._config import BaseObj
    from ngio_collections.models.traits import BaseTrait

ModelType = TypeVar("ModelType", bound="BaseObj")
TraitType = TypeVar("TraitType", bound="BaseTrait")


def trait_key(trait: type[BaseTrait] | str) -> str:
    """Return the trait `type` string for a trait model class or a plain string."""
    return trait if isinstance(trait, str) else trait.trait_type()


def trait_types(record: NodeRecord) -> tuple[str, ...]:
    """Return the trait types `record` carries, in order."""
    return tuple(record.traits)


def has_trait(record: NodeRecord, trait: type[BaseTrait] | str) -> bool:
    """Return whether `record` carries the trait (model class or type string)."""
    return trait_key(trait) in record.traits


def read_trait(record: NodeRecord, trait_type: type[TraitType]) -> TraitType:
    """Validate and return `record`'s trait of `trait_type`.

    Raises:
        KeyError: If the trait is absent.
        pydantic.ValidationError: If the stored value does not validate.
    """
    return trait_type.model_validate(record.traits[trait_type.trait_type()])


def get_trait(record: NodeRecord, trait_type: type[TraitType]) -> TraitType | None:
    """Return the validated trait of `trait_type`, or `None` if absent."""
    if trait_type.trait_type() in record.traits:
        return read_trait(record, trait_type)
    return None


def read_fields(record: NodeRecord, model: type[ModelType]) -> ModelType:
    """Validate and return `record`'s node-type fields as `model`.

    Raises:
        pydantic.ValidationError: If the fields do not validate.
    """
    return model.model_validate(dict(record.fields))
