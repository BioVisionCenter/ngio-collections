"""Capability lenses: read a node's attribute bag through a typed model.

A node carries its semantic roles as entries in its `attributes` dict; each typed
attribute model (`WellAttribute`, `CoordinateSystemsAttribute`, …) declares the
`key` it maps to. These helpers turn a raw entry into the validated model on
demand — the same lazy pattern v4 used, lifted to operate on a `NodeRecord`. They
are *composable*: a node carrying both `well` and `scene` answers `has_attribute`
for each, independently.
"""

from __future__ import annotations

from typing import TypeVar

from ngio_collections.graph import NodeRecord
from ngio_collections.models.attributes import AnyAttribute

A = TypeVar("A", bound=AnyAttribute)


def has_attribute(record: NodeRecord, attr_type: type[A]) -> bool:
    """Return whether `record` carries the capability `attr_type` maps to."""
    return attr_type.key in record.attributes


def read_attribute(record: NodeRecord, attr_type: type[A]) -> A:
    """Validate and return `record`'s value for `attr_type`.

    Raises:
        KeyError: If the attribute is absent.
        pydantic.ValidationError: If the stored value does not validate.
    """
    return attr_type.model_validate(record.attributes[attr_type.key])


def get_attribute(record: NodeRecord, attr_type: type[A]) -> A | None:
    """Return the validated `attr_type` value, or `None` if absent."""
    if attr_type.key in record.attributes:
        return read_attribute(record, attr_type)
    return None
