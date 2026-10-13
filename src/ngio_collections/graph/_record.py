"""`NodeRecord`: the inert storage row for one node in a `NodeTree`.

A record is plain, frozen data — it has no methods that navigate or edit, and it
does not know its own `NodeId`. Its `children` are *keys* (`NodeId`s), not nested
records, which is what lets an edit to one node leave every ancestor untouched.
The public `Node` handle pairs a record's key with its `NodeTree` to offer the
familiar `walk()` / `find()` / `set_attr()` behaviour.

A record is exactly one *shape*:
- **branch** — a declaration with `children` (a tuple, possibly empty);
- **leaf** — a declaration with `children is None` (a multiscale, say);
- **reference** — `ref` is set; no `id`, no `name`, no body, no children.

A *declaration* always carries an `id` (the proposal's UUID, declared once in
the document that holds the body); a *reference* never does — it points at a
declared id through `ref` (plus an optional document `path`). `type` is the
coarse structural tag (`collection` / `multiscale` / custom); on a reference it
repeats the target's type. `attributes` is the node's *body*: every wire key
that is not structural (`type`, `id`, `name`, `nodes`, `ref`, `path`) — traits,
`scales`, `coordinate_systems`, custom keys — kept opaque. `origin_url` records
the document a record came from, for `ref()` and write routing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from ngio_collections._types import JSONValue

from ngio_collections.graph._ids import NodeId
from ngio_collections.models._paths import DocPath

_EMPTY_ATTRS: Mapping[str, JSONValue] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class Reference:
    """A node's pointer: the declared id `ref` and the document `path` to find it in.

    `path` is `None` for a bare reference within the same document (left in
    place, never resolved). This is the *structural* pointer stored on a
    `NodeRecord`; the portable `ReferenceObj` that `node.ref()` returns adds
    the target's `type`.
    """

    ref: str
    path: DocPath | None = None


@dataclass(frozen=True, slots=True)
class NodeRecord:
    """One immutable node row; see the module docstring for the shape invariant."""

    type: str
    name: str | None = None
    id: str | None = None
    attributes: Mapping[str, JSONValue] = field(default=_EMPTY_ATTRS)
    children: tuple[NodeId, ...] | None = None
    ref: Reference | None = None
    origin_url: str | None = None

    def __post_init__(self) -> None:
        """Validate the declaration / reference shape invariant."""
        if self.ref is not None:
            if self.children is not None:
                raise ValueError(
                    f"reference to {self.ref.ref!r} cannot have children; "
                    "a record has children OR a ref, never both"
                )
            if self.id is not None or self.name is not None or self.attributes:
                raise ValueError(
                    f"reference to {self.ref.ref!r} carries only type, ref and "
                    "path; the referenced node brings its own id, name and body"
                )
        elif self.id is None:
            raise ValueError(f"declared {self.type!r} node {self.name!r} needs an id")

    @property
    def is_reference(self) -> bool:
        """True iff this record points at a declared node (here or elsewhere)."""
        return self.ref is not None

    @property
    def is_branch(self) -> bool:
        """True iff this record holds children (an embedded group)."""
        return self.children is not None

    @property
    def is_leaf(self) -> bool:
        """True iff this record is an embedded leaf (no children, no ref)."""
        return self.children is None and self.ref is None
