"""Attribute model base classes.

The attribute protocol: each attribute model declares the `attributes` dict
`key` it maps to (via `_AttributeKey`) and is either an object (`BaseAttribute`)
or an array (`BaseListAttribute`). `BaseNode` references `AnyAttribute` /
`AttributeType` for its typed reads. Pure data — depends only on `BaseObj`.
"""

from __future__ import annotations

from typing import ClassVar, TypeVar

from pydantic import RootModel

from ngio_collections.models._config import BaseObj


class _AttributeKey:
    """Mixin declaring the `attributes` dict key an attribute model maps to."""

    key: ClassVar[str]

    @classmethod
    def name_space(cls) -> str | None:
        """Return the `key`'s namespace prefix (before `:`), or `None`."""
        if ":" in cls.key:
            return cls.key.split(":")[0]
        return None


class BaseAttribute(_AttributeKey, BaseObj):
    """Attribute whose value is a JSON object (e.g. `plate`, `well`)."""


ItemType = TypeVar("ItemType")


class BaseListAttribute(_AttributeKey, RootModel[list[ItemType]]):
    """Attribute whose value is a JSON array (e.g. `coordinateSystems`)."""


AnyAttribute = BaseAttribute | BaseListAttribute
AttributeType = TypeVar("AttributeType", bound=AnyAttribute)
