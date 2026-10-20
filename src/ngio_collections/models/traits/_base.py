"""Trait model base classes (RFC-8 revision 1 §3).

A trait is a typed object a node opts into; `traits` is a list of them and each
carries its own `type` (a keyword for built-in traits, a URI for extension
traits). A trait model fixes that `type` as a `Literal` default, which is both
the serialized field and the key the node handle indexes it under (`node[WellTrait]`,
`node.has_trait("well")`). `applies_to` records which node types may carry the
trait (§3.1); an empty set means any. Pure data: depends only on `BaseObj`.
"""

from __future__ import annotations

from typing import ClassVar, TypeVar

from ngio_collections.models._config import BaseObj
from ngio_collections.models._manifest import is_extension_type


class BaseTrait(BaseObj):
    """Base for trait models; subclasses fix `type: Literal["..."] = "..."`.

    `extra="allow"` (inherited) keeps unknown fields, so a trait a reader only
    partially understands still round-trips.
    """

    applies_to: ClassVar[frozenset[str]] = frozenset()
    """Node types that may carry this trait; empty means any node type."""

    type: str

    @classmethod
    def trait_type(cls) -> str:
        """Return the trait `type` this model fixes.

        Raises:
            TypeError: If the model leaves `type` open (e.g. `UnknownTrait`).
        """
        default = cls.model_fields["type"].default
        if not isinstance(default, str):
            raise TypeError(f"{cls.__name__} does not fix a trait `type`")
        return default

    @classmethod
    def is_extension(cls) -> bool:
        """Return whether this trait's `type` is a URI (an extension trait)."""
        return is_extension_type(cls.trait_type())


class UnknownTrait(BaseTrait):
    """A trait of any `type`; the fallback for traits with no model."""

    type: str


TraitType = TypeVar("TraitType", bound=BaseTrait)
