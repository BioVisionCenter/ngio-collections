"""`NodeTree`: the immutable indexed graph that is the v5 in-memory model.

A `NodeTree` is a value: a persistent `NodeId → NodeRecord` map plus two derived
indices, `by_local_id` (every node carrying a given local `id`) and `refs` (every
node that points at a given id). Because parents hold child *keys*, editing a
node's data is one map write that leaves all ancestors untouched, and `find` is an
index lookup rather than a tree walk.

Every edit returns a *new* `NodeTree` that shares all untouched records with the
old one (the persistent map handles the sharing). Structural edits (`add_child`,
`remove`) also keep the indices in step. Construction is incremental: seed with
`NodeTree.of(root)`, then grow with `add_child`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterator, Literal, Mapping

from pydantic import JsonValue

from ngio_collections.graph._ids import ROOT, NodeId
from ngio_collections.graph._pmap import PersistentMap
from ngio_collections.graph._record import NodeRecord

Mode = Literal["editable", "resolved"]


def _seedable(record: NodeRecord) -> None:
    """Reject a record whose children are pre-populated (build incrementally)."""
    if record.children:
        raise ValueError(
            f"node {record.id!r} must be added empty; attach its children with "
            "add_child rather than pre-filling the children tuple"
        )


def _index_add(
    index: PersistentMap[str, tuple[NodeId, ...]], key: str | None, nid: NodeId
) -> PersistentMap[str, tuple[NodeId, ...]]:
    """Append `nid` to the bucket for `key` (no-op when `key` is `None`)."""
    if key is None:
        return index
    return index.set(key, (*index.get(key, ()), nid))


def _index_remove(
    index: PersistentMap[str, tuple[NodeId, ...]], key: str | None, nid: NodeId
) -> PersistentMap[str, tuple[NodeId, ...]]:
    """Drop `nid` from the bucket for `key`, pruning the bucket if it empties."""
    if key is None:
        return index
    current = index.get(key)
    if not current:
        return index
    remaining = tuple(n for n in current if n != nid)
    return index.set(key, remaining) if remaining else index.delete(key)


def _ref_key(record: NodeRecord) -> str | None:
    """The id this record references, or `None` if it is not a reference."""
    return record.ref.id if record.ref is not None else None


def _segment_for(siblings: tuple[NodeId, ...], record: NodeRecord) -> str:
    """Pick a path segment unique among `siblings` (prefer the local id)."""
    taken = {sib[-1] for sib in siblings}
    if record.id is not None and record.id not in taken:
        return record.id
    i = len(siblings)
    while str(i) in taken:
        i += 1
    return str(i)


def _bucket_add(
    buckets: dict[str, tuple[NodeId, ...]], key: str | None, nid: NodeId
) -> None:
    """Append `nid` to the in-place `buckets` for `key` (no-op when `key` is None)."""
    if key is not None:
        buckets[key] = (*buckets.get(key, ()), nid)


@dataclass(frozen=True, slots=True)
class NodeTree:
    """An immutable graph of `NodeRecord`s keyed by `NodeId`; see module docstring."""

    root: NodeId
    nodes: PersistentMap[NodeId, NodeRecord]
    by_local_id: PersistentMap[str, tuple[NodeId, ...]]
    refs: PersistentMap[str, tuple[NodeId, ...]]
    mode: Mode = "editable"

    # -- construction -------------------------------------------------------

    @classmethod
    def of(cls, root: NodeRecord, *, mode: Mode = "editable") -> NodeTree:
        """Return a single-node collection rooted at `root` (added empty)."""
        _seedable(root)
        seeded = replace(root, children=() if root.children is not None else None)
        return cls(
            root=ROOT,
            nodes=PersistentMap({ROOT: seeded}),
            by_local_id=_index_add(PersistentMap(), seeded.id, ROOT),
            refs=_index_add(PersistentMap(), _ref_key(seeded), ROOT),
            mode=mode,
        )

    # -- reads --------------------------------------------------------------

    def record(self, node_id: NodeId) -> NodeRecord:
        """Return the record at `node_id`, raising `KeyError` if absent."""
        return self.nodes[node_id]

    def get(self, node_id: NodeId) -> NodeRecord | None:
        """Return the record at `node_id`, or `None` if absent."""
        return self.nodes.get(node_id)

    def __contains__(self, node_id: object) -> bool:
        """Return whether `node_id` is present."""
        return node_id in self.nodes

    def __len__(self) -> int:
        """Return the number of nodes in the collection."""
        return len(self.nodes)

    def children_ids(self, node_id: NodeId) -> tuple[NodeId, ...]:
        """Return the child keys of `node_id` (empty for a leaf or reference)."""
        return self.nodes[node_id].children or ()

    def parent_id(self, node_id: NodeId) -> NodeId | None:
        """Return the parent key, or `None` for the root."""
        return node_id[:-1] if node_id else None

    def walk(self, start: NodeId | None = None) -> Iterator[NodeId]:
        """Yield `start` (default root) and every descendant, depth-first in order."""
        stack = [self.root if start is None else start]
        while stack:
            node_id = stack.pop()
            yield node_id
            children = self.nodes[node_id].children
            if children:
                stack.extend(reversed(children))

    def find(self, local_id: str) -> tuple[NodeId, ...]:
        """Return every `NodeId` whose record carries `local_id` (index lookup)."""
        return self.by_local_id.get(local_id, ())

    def referrers(self, local_id: str) -> tuple[NodeId, ...]:
        """Return every `NodeId` whose record references `local_id`."""
        return self.refs.get(local_id, ())

    # -- structural edits ---------------------------------------------------

    def add_child(
        self, parent_id: NodeId, record: NodeRecord
    ) -> tuple[NodeTree, NodeId]:
        """Attach `record` under `parent_id`; return the new collection and child key.

        This copies the node map (O(n)); to build a whole tree in one pass use
        `TreeBuilder` instead, which is O(n) overall.
        """
        _seedable(record)
        parent = self.nodes[parent_id]
        if parent.is_reference:
            raise ValueError(f"cannot add a child to reference node {parent_id}")
        child_rec = replace(record, children=() if record.children is not None else None)
        siblings = parent.children or ()
        child_key = (*parent_id, _segment_for(siblings, child_rec))

        evolver = self.nodes.mutate()
        evolver.set(child_key, child_rec)
        evolver.set(parent_id, replace(parent, children=(*siblings, child_key)))

        by_local_id = _index_add(self.by_local_id, child_rec.id, child_key)
        refs = _index_add(self.refs, _ref_key(child_rec), child_key)
        new = replace(self, nodes=evolver.finish(), by_local_id=by_local_id, refs=refs)
        return new, child_key

    def remove(self, node_id: NodeId) -> NodeTree:
        """Remove the subtree at `node_id` and unlink it from its parent.

        Idempotent: removing an absent node returns the collection unchanged.
        The root cannot be removed.
        """
        if node_id == self.root:
            raise ValueError("cannot remove the root node")
        if node_id not in self.nodes:
            return self

        evolver = self.nodes.mutate()
        by_local_id = self.by_local_id
        refs = self.refs
        for descendant in tuple(self.walk(node_id)):
            rec = self.nodes[descendant]
            evolver.delete(descendant)
            by_local_id = _index_remove(by_local_id, rec.id, descendant)
            refs = _index_remove(refs, _ref_key(rec), descendant)

        parent_key = node_id[:-1]
        parent = self.nodes[parent_key]
        kept = tuple(c for c in (parent.children or ()) if c != node_id)
        evolver.set(parent_key, replace(parent, children=kept))
        return replace(self, nodes=evolver.finish(), by_local_id=by_local_id, refs=refs)

    # -- data edits (structure-preserving; indices unchanged) ---------------

    def set_attributes(
        self, node_id: NodeId, attributes: Mapping[str, JsonValue]
    ) -> NodeTree:
        """Replace the whole attribute bag of `node_id`."""
        rec = self.nodes[node_id]
        return replace(self, nodes=self.nodes.set(node_id, replace(rec, attributes=dict(attributes))))

    def set_attrs(
        self, node_id: NodeId, values: Mapping[str, JsonValue]
    ) -> NodeTree:
        """Merge `values` into the attribute bag of `node_id`."""
        rec = self.nodes[node_id]
        merged = {**rec.attributes, **values}
        return replace(self, nodes=self.nodes.set(node_id, replace(rec, attributes=merged)))

    def drop_attrs(self, node_id: NodeId, keys: tuple[str, ...]) -> NodeTree:
        """Remove `keys` from the attribute bag of `node_id` (missing keys ignored)."""
        rec = self.nodes[node_id]
        remaining = {k: v for k, v in rec.attributes.items() if k not in keys}
        return replace(self, nodes=self.nodes.set(node_id, replace(rec, attributes=remaining)))

    def rename(self, node_id: NodeId, name: str | None) -> NodeTree:
        """Set the display `name` of `node_id`."""
        rec = self.nodes[node_id]
        return replace(self, nodes=self.nodes.set(node_id, replace(rec, name=name)))


class TreeBuilder:
    """A mutable accumulator that builds a `NodeTree` in one O(n) pass.

    `NodeTree.add_child` returns a new tree each call (copying the node map), so
    adding n nodes that way is O(n²). When constructing a whole tree at once —
    parsing a document in `build`, or generating a large tree — stage the nodes
    here (each `add_child` is O(1) amortised) and `finish()` once. Single-use:
    after `finish()` the builder is spent (its dicts back the new tree).
    """

    __slots__ = ("_nodes", "_by_local_id", "_refs", "_mode", "_done")

    def __init__(self, root: NodeRecord, *, mode: Mode = "editable") -> None:
        """Start a builder seeded with `root` (added empty, as `NodeTree.of`)."""
        _seedable(root)
        seeded = replace(root, children=() if root.children is not None else None)
        self._nodes: dict[NodeId, NodeRecord] = {ROOT: seeded}
        self._by_local_id: dict[str, tuple[NodeId, ...]] = {}
        self._refs: dict[str, tuple[NodeId, ...]] = {}
        self._mode = mode
        self._done = False
        _bucket_add(self._by_local_id, seeded.id, ROOT)
        _bucket_add(self._refs, _ref_key(seeded), ROOT)

    def _check(self) -> None:
        if self._done:
            raise RuntimeError("TreeBuilder already finished; it is single-use")

    def add_child(self, parent_key: NodeId, record: NodeRecord) -> NodeId:
        """Attach `record` under `parent_key` in place; return the new child key."""
        self._check()
        parent = self._nodes[parent_key]
        if parent.is_reference:
            raise ValueError(f"cannot add a child to reference node {parent_key}")
        child_rec = replace(record, children=() if record.children is not None else None)
        siblings = parent.children or ()
        child_key = (*parent_key, _segment_for(siblings, child_rec))
        self._nodes[child_key] = child_rec
        self._nodes[parent_key] = replace(parent, children=(*siblings, child_key))
        _bucket_add(self._by_local_id, child_rec.id, child_key)
        _bucket_add(self._refs, _ref_key(child_rec), child_key)
        return child_key

    def finish(self) -> NodeTree:
        """Freeze the staged nodes into a `NodeTree` and spend this builder."""
        self._check()
        self._done = True
        return NodeTree(
            root=ROOT,
            nodes=PersistentMap(self._nodes, _own=True),
            by_local_id=PersistentMap(self._by_local_id, _own=True),
            refs=PersistentMap(self._refs, _own=True),
            mode=self._mode,
        )
