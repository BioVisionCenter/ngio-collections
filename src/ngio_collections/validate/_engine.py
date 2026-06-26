"""The scoped, composable validator engine.

A validator declares the bounded neighbourhood it reads (a `Scope`) and runs over
a `Context` — a focus node paired with cheap, index-backed navigation (parent,
ancestors, children, descendants) and the capability lenses. Validators register
independently and *compose*: `validate` runs the union of every validator that
applies to a node, so a node carrying both `well` and `scene` runs both sets with
no combinatorial classes. Each validator touches only its declared neighbourhood,
never the whole collection, so checking one node stays cheap even at 1M nodes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Protocol, TypeVar, runtime_checkable

from ngio_collections.graph import NodeTree, NodeId
from ngio_collections.models.attributes import AnyAttribute
from ngio_collections.validate._views import get_attribute, has_attribute, read_attribute

A = TypeVar("A", bound=AnyAttribute)


@dataclass(frozen=True, slots=True)
class Scope:
    """The bounded neighbourhood a validator reads (documentation of its cost).

    `ancestors` / `descendants` are how many levels up / down the check looks
    (`0` none, a positive int that many levels, `None` unbounded but still local
    in practice); `refs` flags that it follows reference ids within attributes.
    """

    ancestors: int | None = 0
    descendants: int | None = 0
    refs: bool = False


@dataclass(frozen=True, slots=True)
class Issue:
    """A single validation finding: which node, which validator, what is wrong."""

    node_id: NodeId
    validator: str
    message: str


class Context:
    """A focus node plus bounded navigation and capability lenses over it."""

    __slots__ = ("collection", "node_id")

    def __init__(self, collection: NodeTree, node_id: NodeId) -> None:
        """Bind the focus `node_id` within `collection`."""
        self.collection = collection
        self.node_id = node_id

    @property
    def record(self):  # -> NodeRecord
        """The focus node's record."""
        return self.collection.record(self.node_id)

    @property
    def parent(self) -> Context | None:
        """The parent context, or `None` at the root."""
        if not self.node_id:
            return None
        return Context(self.collection, self.node_id[:-1])

    def ancestors(self) -> Iterator[Context]:
        """Yield the parent, grandparent, … up to and including the root."""
        node_id = self.node_id
        while node_id:
            node_id = node_id[:-1]
            yield Context(self.collection, node_id)

    def children(self) -> Iterator[Context]:
        """Yield each direct child context."""
        for child_id in self.collection.children_ids(self.node_id):
            yield Context(self.collection, child_id)

    def descendants(self) -> Iterator[Context]:
        """Yield every descendant context (excludes self), depth-first."""
        walk = self.collection.walk(self.node_id)
        next(walk, None)  # skip self
        for node_id in walk:
            yield Context(self.collection, node_id)

    def has(self, attr_type: type[A]) -> bool:
        """Return whether the focus node carries `attr_type`'s capability."""
        return has_attribute(self.record, attr_type)

    def view(self, attr_type: type[A]) -> A:
        """Validate and return the focus node's `attr_type` value."""
        return read_attribute(self.record, attr_type)

    def get(self, attr_type: type[A]) -> A | None:
        """Return the focus node's `attr_type` value, or `None` if absent."""
        return get_attribute(self.record, attr_type)


@runtime_checkable
class Validator(Protocol):
    """A check that applies to some nodes and reads a bounded neighbourhood."""

    name: str
    scope: Scope

    def applies(self, ctx: Context) -> bool:
        """Return whether this validator should run on `ctx`'s focus node."""
        ...

    def check(self, ctx: Context) -> Iterable[Issue]:
        """Yield an `Issue` for each problem found in `ctx`'s neighbourhood."""
        ...


class CapabilityValidator:
    """Base validator that applies when the focus node carries `capability`."""

    name: str
    scope: Scope
    capability: type[AnyAttribute]

    def applies(self, ctx: Context) -> bool:
        """Apply when the focus node carries `self.capability`."""
        return ctx.has(self.capability)

    def check(self, ctx: Context) -> Iterable[Issue]:
        """Subclasses implement the actual check."""
        raise NotImplementedError


class ValidatorRegistry:
    """An ordered set of validators; `applicable` filters them per node."""

    def __init__(self) -> None:
        """Start an empty registry."""
        self._validators: list[Validator] = []

    def register(self, validator: Validator) -> Validator:
        """Add `validator` to the registry and return it."""
        self._validators.append(validator)
        return validator

    def applicable(self, ctx: Context) -> Iterator[Validator]:
        """Yield every registered validator that applies to `ctx`."""
        return (v for v in self._validators if v.applies(ctx))

    def __iter__(self) -> Iterator[Validator]:
        """Iterate over every registered validator."""
        return iter(self._validators)


DEFAULT_VALIDATORS = ValidatorRegistry()


def validate(
    collection: NodeTree,
    node_id: NodeId,
    *,
    registry: ValidatorRegistry | None = None,
) -> list[Issue]:
    """Run every applicable validator on one node; return the issues found."""
    registry = registry if registry is not None else DEFAULT_VALIDATORS
    ctx = Context(collection, node_id)
    issues: list[Issue] = []
    for validator in registry.applicable(ctx):
        issues.extend(validator.check(ctx))
    return issues


def validate_tree(
    collection: NodeTree, *, registry: ValidatorRegistry | None = None
) -> list[Issue]:
    """Validate every node in `collection` (each scan stays node-local)."""
    issues: list[Issue] = []
    for node_id in collection.walk():
        issues.extend(validate(collection, node_id, registry=registry))
    return issues
