"""`NodeRecord`: the inert storage row for one node in a `NodeTree`.

A record is plain, frozen data — it has no methods that navigate or edit, and it
does not know its own `NodeId`. Its `children` are *keys* (`NodeId`s), not nested
records, which is what lets an edit to one node leave every ancestor untouched.
The public `Node` handle pairs a record's key with its `NodeTree` to offer the
familiar `walk()` / `find()` / `set_attr()` behaviour.

A record is exactly one *shape*:
- **branch** — `children` is a tuple (possibly empty), `ref` is `None`;
- **leaf** — `children` is `None`, `ref` is `None`;
- **reference** — `ref` is set, `children` is `None`.

`type` is the coarse structural tag (`collection` / `multiscale` / `singlescale`
/ custom). Semantic roles (`well`, `scene`, `plate`, …) are *not* types: they are
composable capability entries in `attributes`, so one node can carry several at
once. `id` is the node's original local id, kept verbatim and never rewritten;
`origin_url` records the document it came from, for `ref()` and write routing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from pydantic import JsonValue

from ngio_collections.graph._ids import NodeId
from ngio_collections.models._paths import DocPath

_EMPTY_ATTRS: Mapping[str, JsonValue] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class Reference:
    """A node's external pointer: a document `path` and an optional target `id`.

    `path` is required (the document to load); `id` is the local id to find inside
    it, or `None` to mean "that document's root" (an RFC-8 doc-root stub). This is
    the *structural* pointer stored on a `NodeRecord`; the portable `ReferenceObj`
    that `node.ref()` returns is a separate, id-required locator minted on demand.
    """

    path: DocPath
    id: str | None = None


@dataclass(frozen=True, slots=True)
class EdgeInfo:
    """Provenance of an inlined boundary node: the reference edge it collapsed.

    Retained when inlining splices a stub's target into the tree, so the §5
    attribute merge stays invertible (edge keeps overrides): `ref` is the stub's
    pointer, `attributes` / `name` are the stub's own pre-merge values, and
    `origin_url` is the document that declared the stub. This is groundwork for
    per-document write-back of resolved trees (`save_tree`).
    """

    ref: Reference
    attributes: Mapping[str, JsonValue] = field(default=_EMPTY_ATTRS)
    name: str | None = None
    origin_url: str | None = None


@dataclass(frozen=True, slots=True)
class NodeRecord:
    """One immutable node row; see the module docstring for the shape invariant."""

    type: str
    name: str | None = None
    id: str | None = None
    attributes: Mapping[str, JsonValue] = field(default=_EMPTY_ATTRS)
    children: tuple[NodeId, ...] | None = None
    ref: Reference | None = None
    origin_url: str | None = None
    edge: EdgeInfo | None = None

    def __post_init__(self) -> None:
        """Validate the branch / leaf / reference shape invariant."""
        if self.children is not None and self.ref is not None:
            raise ValueError(
                f"node {self.id!r} is both a branch and a reference; "
                "a record has children OR a ref, never both"
            )

    @property
    def is_reference(self) -> bool:
        """True iff this record points at another document."""
        return self.ref is not None

    @property
    def is_branch(self) -> bool:
        """True iff this record holds children (an embedded group)."""
        return self.children is not None

    @property
    def is_leaf(self) -> bool:
        """True iff this record is an embedded leaf (no children, no ref)."""
        return self.children is None and self.ref is None
