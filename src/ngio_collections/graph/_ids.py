"""`NodeId`: the structural path key that identifies a node in a `NodeTree`.

A `NodeId` is a tuple of string segments naming the path from the root, e.g.
`("img",)` or `("labels", "nuclei")`; the root is the empty tuple. Identity is
*positional*, so the same on-disk document inlined under two parents gets two
distinct `NodeId`s without any id rewriting — the node's own local `id` stays
pristine as data on its `NodeRecord`.

Each segment is unique among its siblings (it is the child's local `id` when that
is free, else a positional fallback); see `NodeTree._segment_for`. Because the
path encodes ancestry, `parent` is just `id[:-1]` — no parent index is stored.
"""

from __future__ import annotations

NodeId = tuple[str, ...]

ROOT: NodeId = ()


def parent(node_id: NodeId) -> NodeId | None:
    """Return the parent `NodeId`, or `None` for the root."""
    return node_id[:-1] if node_id else None


def child(parent_id: NodeId, segment: str) -> NodeId:
    """Return the `NodeId` of the child reached from `parent_id` via `segment`."""
    return (*parent_id, segment)


def depth(node_id: NodeId) -> int:
    """Return the depth of `node_id` (root is 0)."""
    return len(node_id)


def is_ancestor(ancestor: NodeId, descendant: NodeId) -> bool:
    """Return whether `ancestor` is a strict ancestor of `descendant`."""
    return len(ancestor) < len(descendant) and descendant[: len(ancestor)] == ancestor
