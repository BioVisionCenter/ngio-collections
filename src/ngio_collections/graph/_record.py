"""`NodeRecord`: the inert storage row for one node in a `NodeTree`.

A record is plain, frozen data: it has no methods that navigate or edit, and it
does not know its own `NodeId`. Its `children` are *keys* (`NodeId`s), not nested
records, which is what lets an edit to one node leave every ancestor untouched.
The public `Node` handle pairs a record's key with its `NodeTree` to offer the
familiar `walk()` / `find()` / `set_trait()` behaviour.

A record is exactly one *shape*:
- **branch**: `children` is a tuple (possibly empty), `path` is `None`;
- **leaf**: `children` is `None`, `path` is `None`;
- **external**: `path` is set, `children` is `None` (the node is declared here
  but its document lives elsewhere; a multiscale in a collection is always one).

`type` is the structural tag (`collection` / `multiscale` / an extension URI).
Semantic roles (`well`, `scene`, `plate`, …) are *traits*: typed objects keyed
by their own `type`, so one node can carry several at once. Node-type fields
that RFC-8 revision 1 puts directly on the node (`coordinate_systems`, `scales`,
extension fields) live in `fields`. `id` is the node's UUID, kept verbatim and
never rewritten; `origin_url` records the document it came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterator, Literal, Mapping, Sequence

from ngio_collections._types import JSONValue
from ngio_collections.graph._ids import NodeId
from ngio_collections.models._paths import DocPath

Traits = Mapping[str, Mapping[str, JSONValue]]
"""Trait type → the trait object verbatim (its `type` key included), in order."""

Fields = Mapping[str, JSONValue]
"""Node-type fields (`coordinate_systems`, `scales`, extension fields)."""

_EMPTY: Mapping = MappingProxyType({})

RESERVED_NODE_KEYS = frozenset({"type", "id", "name", "traits", "nodes", "path"})
"""Node-dict keys the record models itself; everything else is a field."""


def traits_from_list(
    items: Sequence[Mapping[str, JSONValue]] | None,
    *,
    on_duplicate: Literal["raise", "last"] = "raise",
) -> Traits:
    """Index a wire `traits` list by trait `type`.

    Args:
        items: The `traits` array as read from a node dict (or `None`).
        on_duplicate: `"raise"` rejects two traits of one type; `"last"` keeps
            the last one (lenient loading of invalid documents).

    Returns:
        An insertion-ordered mapping of trait type → trait object.

    Raises:
        ValueError: If an item is not an object with a string `type`, or a type
            repeats and `on_duplicate == "raise"`.
    """
    out: dict[str, Mapping[str, JSONValue]] = {}
    for item in items or ():
        trait_type = item.get("type") if isinstance(item, Mapping) else None
        if not isinstance(trait_type, str):
            raise ValueError(
                f"a trait must be an object with a string `type`: {item!r}"
            )
        if trait_type in out and on_duplicate == "raise":
            raise ValueError(f"duplicate trait type {trait_type!r} on one node")
        out[trait_type] = item
    return out


def traits_to_list(traits: Traits) -> list[dict[str, JSONValue]]:
    """Return the wire `traits` array for an indexed trait mapping."""
    return [dict(trait) for trait in traits.values()]


def merge_traits(base: Traits, override: Traits) -> Traits:
    """Combine two trait sets; `override` wins per trait type (RFC-8 rev. 1 §3.1).

    The result keeps `base`'s order, replaces same-type entries in place, and
    appends the types only `override` carries.
    """
    if not override:
        return base
    if not base:
        return override
    return {**base, **override}


def _walk_declarations(value: object) -> Iterator[Mapping[str, JSONValue]]:
    """Yield every `{type, id}` declaration object nested anywhere in `value`."""
    if isinstance(value, Mapping):
        if isinstance(value.get("type"), str) and isinstance(value.get("id"), str):
            yield value
        for item in value.values():
            yield from _walk_declarations(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_declarations(item)


def iter_declarations(record: NodeRecord) -> Iterator[Mapping[str, JSONValue]]:
    """Yield every `{type, id}` declaration nested in `record`'s fields and traits."""
    for container in (record.fields, record.traits):
        yield from _walk_declarations(dict(container))


def declared_ids(record: NodeRecord) -> tuple[str, ...]:
    """Return the ids of the declarations nested in `record`'s fields and traits.

    These are the scales, coordinate systems, acquisitions, … that same-document
    references (`{type, ref}`) point at. The node's own id and its children are
    not included.
    """
    ids: list[str] = []
    for container in (record.fields, record.traits):
        for declaration in _walk_declarations(dict(container)):
            ids.append(str(declaration["id"]))
    return tuple(ids)


def find_declaration(record: NodeRecord, uuid: str) -> Mapping[str, JSONValue] | None:
    """Return the first `{type, id}` object with `id == uuid` nested in `record`."""
    for container in (record.fields, record.traits):
        for declaration in _walk_declarations(dict(container)):
            if declaration["id"] == uuid:
                return declaration
    return None


@dataclass(frozen=True, slots=True)
class EdgeInfo:
    """Provenance of a resolved boundary node: the declaring entry it collapsed.

    Retained when resolution splices an external node's target document in, so
    the §3.1 trait combination stays invertible: `path` is the declaring entry's
    locator, `traits` / `fields` / `name` are its own pre-merge values, and
    `origin_url` is the document that declared it. Serializing a record with an
    `edge` emits that declaring entry again, never the target's subtree.
    """

    path: DocPath
    traits: Traits = field(default=_EMPTY)
    fields: Fields = field(default=_EMPTY)
    name: str | None = None
    origin_url: str | None = None


@dataclass(frozen=True, slots=True)
class NodeRecord:
    """One immutable node row; see the module docstring for the shape invariant."""

    type: str
    id: str
    name: str | None = None
    traits: Traits = field(default=_EMPTY)
    fields: Fields = field(default=_EMPTY)
    children: tuple[NodeId, ...] | None = None
    path: DocPath | None = None
    origin_url: str | None = None
    edge: EdgeInfo | None = None

    def __post_init__(self) -> None:
        """Validate the id, the trait index and the branch / leaf / external shape."""
        if not isinstance(self.id, str) or not self.id:
            raise ValueError(f"node of type {self.type!r} needs a non-empty string id")
        if self.children is not None and self.path is not None:
            raise ValueError(
                f"node {self.id!r} is both a branch and external; "
                "a record has children OR a path, never both"
            )
        for key, trait in self.traits.items():
            if trait.get("type") != key:
                raise ValueError(
                    f"trait indexed under {key!r} carries type {trait.get('type')!r}"
                )

    @property
    def is_external(self) -> bool:
        """True iff this record points at another document."""
        return self.path is not None

    @property
    def is_branch(self) -> bool:
        """True iff this record holds children (an embedded group)."""
        return self.children is not None

    @property
    def is_leaf(self) -> bool:
        """True iff this record is an embedded leaf (no children, no path)."""
        return self.children is None and self.path is None
