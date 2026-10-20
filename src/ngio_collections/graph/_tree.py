"""`NodeTree`: the immutable indexed graph that is the in-memory model.

A `NodeTree` is a value: a persistent `NodeId → NodeRecord` map plus two derived
indices, `by_local_id` (every node carrying a given `id`) and `by_declaration_id`
(every node whose fields or traits *declare* a given id: a scale, a coordinate
system, an acquisition). Because parents hold child *keys*, editing a node's data
is one map write that leaves all ancestors untouched, and `find` is an index
lookup rather than a tree walk.

Every edit returns a *new* `NodeTree` that shares all untouched records with the
old one (the persistent map handles the sharing). Structural edits (`add_child`,
`remove`, `replace`) and data edits that change declarations keep the indices in
step. Construction is incremental: seed with `NodeTree.of(root)`, then grow with
`add_child`; or stage a whole tree in one pass with `TreeBuilder`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, Iterator, Literal, Mapping

from ngio_collections._types import JSONValue
from ngio_collections.graph._ids import ROOT, NodeId
from ngio_collections.graph._pmap import PersistentMap
from ngio_collections.graph._record import Fields, NodeRecord, Traits, declared_ids

Mode = Literal["editable", "resolved"]

_Index = PersistentMap[str, tuple[NodeId, ...]]


def _seedable(record: NodeRecord) -> None:
    """Reject a record whose children are pre-populated (build incrementally)."""
    if record.children:
        raise ValueError(
            f"node {record.id!r} must be added empty; attach its children with "
            "add_child rather than pre-filling the children tuple"
        )


def _index_add(index: _Index, keys: Iterable[str], nid: NodeId) -> _Index:
    """Append `nid` to the bucket of every key in `keys`."""
    for key in keys:
        index = index.set(key, (*index.get(key, ()), nid))
    return index


def _index_remove(index: _Index, keys: Iterable[str], nid: NodeId) -> _Index:
    """Drop `nid` from the bucket of every key in `keys`, pruning empty buckets."""
    for key in keys:
        current = index.get(key)
        if not current:
            continue
        remaining = tuple(n for n in current if n != nid)
        index = index.set(key, remaining) if remaining else index.delete(key)
    return index


def _segment_for(siblings: tuple[NodeId, ...], record: NodeRecord) -> str:
    """Pick a path segment unique among `siblings` (the id unless a sibling took it)."""
    taken = {sib[-1] for sib in siblings}
    if record.id not in taken:
        return record.id
    i = len(siblings)
    while str(i) in taken:
        i += 1
    return str(i)


def _bucket_add(
    buckets: dict[str, tuple[NodeId, ...]], keys: Iterable[str], nid: NodeId
) -> None:
    """Append `nid` to the in-place `buckets` of every key in `keys`."""
    for key in keys:
        buckets[key] = (*buckets.get(key, ()), nid)


@dataclass(frozen=True, slots=True)
class NodeTree:
    """An immutable graph of `NodeRecord`s keyed by `NodeId`; see module docstring."""

    root: NodeId
    nodes: PersistentMap[NodeId, NodeRecord]
    by_local_id: _Index
    by_declaration_id: _Index
    mode: Mode = "editable"
    manifests: Mapping[str, tuple[dict, ...]] = field(default_factory=dict)
    """Per document URL, the `extension_manifest` it was read with."""

    # -- construction -------------------------------------------------------

    @classmethod
    def of(cls, root: NodeRecord, *, mode: Mode = "editable") -> NodeTree:
        """Return a single-node tree rooted at `root` (added empty)."""
        _seedable(root)
        seeded = replace(root, children=() if root.children is not None else None)
        return cls(
            root=ROOT,
            nodes=PersistentMap({ROOT: seeded}),
            by_local_id=_index_add(PersistentMap(), (seeded.id,), ROOT),
            by_declaration_id=_index_add(PersistentMap(), declared_ids(seeded), ROOT),
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
        """Return the number of nodes in the tree."""
        return len(self.nodes)

    def children_ids(self, node_id: NodeId) -> tuple[NodeId, ...]:
        """Return the child keys of `node_id` (empty for a leaf or external node)."""
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

    def declarations(self, uuid: str) -> tuple[NodeId, ...]:
        """Return every `NodeId` whose fields or traits declare `uuid`."""
        return self.by_declaration_id.get(uuid, ())

    # -- structural edits ---------------------------------------------------

    def add_child(
        self, parent_id: NodeId, record: NodeRecord
    ) -> tuple[NodeTree, NodeId]:
        """Attach `record` under `parent_id`; return the new tree and child key.

        This copies the node map (O(n)); to build a whole tree in one pass use
        `TreeBuilder` instead, which is O(n) overall.
        """
        _seedable(record)
        parent = self.nodes[parent_id]
        if parent.is_external:
            raise ValueError(f"cannot add a child to external node {parent_id}")
        child_rec = replace(
            record, children=() if record.children is not None else None
        )
        siblings = parent.children or ()
        child_key = (*parent_id, _segment_for(siblings, child_rec))

        evolver = self.nodes.mutate()
        evolver.set(child_key, child_rec)
        evolver.set(parent_id, replace(parent, children=(*siblings, child_key)))

        new = replace(
            self,
            nodes=evolver.finish(),
            by_local_id=_index_add(self.by_local_id, (child_rec.id,), child_key),
            by_declaration_id=_index_add(
                self.by_declaration_id, declared_ids(child_rec), child_key
            ),
        )
        return new, child_key

    def remove(self, node_id: NodeId) -> NodeTree:
        """Remove the subtree at `node_id` and unlink it from its parent.

        Idempotent: removing an absent node returns the tree unchanged.
        The root cannot be removed.
        """
        if node_id == self.root:
            raise ValueError("cannot remove the root node")
        if node_id not in self.nodes:
            return self

        evolver = self.nodes.mutate()
        by_local_id = self.by_local_id
        by_declaration_id = self.by_declaration_id
        for descendant in tuple(self.walk(node_id)):
            rec = self.nodes[descendant]
            evolver.delete(descendant)
            by_local_id = _index_remove(by_local_id, (rec.id,), descendant)
            by_declaration_id = _index_remove(
                by_declaration_id, declared_ids(rec), descendant
            )

        parent_key = node_id[:-1]
        parent = self.nodes[parent_key]
        kept = tuple(c for c in (parent.children or ()) if c != node_id)
        evolver.set(parent_key, replace(parent, children=kept))
        return replace(
            self,
            nodes=evolver.finish(),
            by_local_id=by_local_id,
            by_declaration_id=by_declaration_id,
        )

    def replace(self, node_id: NodeId, record: NodeRecord) -> NodeTree:
        """Replace the subtree at `node_id` with the single `record`, in place.

        The node keeps its `NodeId` (and therefore its sibling position; the
        parent's children tuple is untouched) while its old record and every
        descendant are removed. `record` is seeded empty like `add_child`.
        """
        _seedable(record)
        self.nodes[node_id]  # KeyError if absent
        new_rec = replace(record, children=() if record.children is not None else None)
        evolver = self.nodes.mutate()
        by_local_id = self.by_local_id
        by_declaration_id = self.by_declaration_id
        for descendant in tuple(self.walk(node_id)):
            rec = self.nodes[descendant]
            evolver.delete(descendant)
            by_local_id = _index_remove(by_local_id, (rec.id,), descendant)
            by_declaration_id = _index_remove(
                by_declaration_id, declared_ids(rec), descendant
            )
        evolver.set(node_id, new_rec)
        by_local_id = _index_add(by_local_id, (new_rec.id,), node_id)
        by_declaration_id = _index_add(
            by_declaration_id, declared_ids(new_rec), node_id
        )
        return replace(
            self,
            nodes=evolver.finish(),
            by_local_id=by_local_id,
            by_declaration_id=by_declaration_id,
        )

    # -- data edits (structure-preserving) ----------------------------------

    def _set_record(self, node_id: NodeId, new_rec: NodeRecord) -> NodeTree:
        """Swap one record, re-indexing its declarations if they changed."""
        old_rec = self.nodes[node_id]
        before, after = declared_ids(old_rec), declared_ids(new_rec)
        index = self.by_declaration_id
        if before != after:
            index = _index_add(_index_remove(index, before, node_id), after, node_id)
        return replace(
            self, nodes=self.nodes.set(node_id, new_rec), by_declaration_id=index
        )

    def set_traits(self, node_id: NodeId, traits: Traits) -> NodeTree:
        """Replace the whole trait set of `node_id`."""
        rec = self.nodes[node_id]
        return self._set_record(node_id, replace(rec, traits=dict(traits)))

    def set_trait(self, node_id: NodeId, trait: Mapping[str, JSONValue]) -> NodeTree:
        """Upsert one trait on `node_id`, keyed by its `type` (in place if present)."""
        trait_type = trait.get("type")
        if not isinstance(trait_type, str):
            raise ValueError(f"a trait must carry a string `type`: {trait!r}")
        rec = self.nodes[node_id]
        return self._set_record(
            node_id, replace(rec, traits={**rec.traits, trait_type: trait})
        )

    def drop_traits(self, node_id: NodeId, types: tuple[str, ...]) -> NodeTree:
        """Remove the traits of the given `types` from `node_id` (missing ignored)."""
        rec = self.nodes[node_id]
        remaining = {k: v for k, v in rec.traits.items() if k not in types}
        return self._set_record(node_id, replace(rec, traits=remaining))

    def set_fields(self, node_id: NodeId, fields: Fields) -> NodeTree:
        """Replace the node-type fields of `node_id`."""
        rec = self.nodes[node_id]
        return self._set_record(node_id, replace(rec, fields=dict(fields)))

    def rename(self, node_id: NodeId, name: str | None) -> NodeTree:
        """Set the display `name` of `node_id`."""
        rec = self.nodes[node_id]
        return replace(self, nodes=self.nodes.set(node_id, replace(rec, name=name)))


class TreeBuilder:
    """A mutable accumulator that builds a `NodeTree` in one O(n) pass.

    `NodeTree.add_child` returns a new tree each call (copying the node map), so
    adding n nodes that way is O(n²). When constructing a whole tree at once
    (parsing a document in `build`, or generating a large tree) stage the nodes
    here (each `add_child` is O(1) amortised) and `finish()` once. Single-use:
    after `finish()` the builder is spent (its dicts back the new tree).
    """

    __slots__ = (
        "_nodes",
        "_by_local_id",
        "_by_declaration_id",
        "_mode",
        "_manifests",
        "_done",
    )

    def __init__(
        self,
        root: NodeRecord,
        *,
        mode: Mode = "editable",
        manifests: Mapping[str, tuple[dict, ...]] | None = None,
    ) -> None:
        """Start a builder seeded with `root` (added empty, as `NodeTree.of`)."""
        _seedable(root)
        seeded = replace(root, children=() if root.children is not None else None)
        self._nodes: dict[NodeId, NodeRecord] = {ROOT: seeded}
        self._by_local_id: dict[str, tuple[NodeId, ...]] = {}
        self._by_declaration_id: dict[str, tuple[NodeId, ...]] = {}
        self._mode = mode
        self._manifests = dict(manifests or {})
        self._done = False
        _bucket_add(self._by_local_id, (seeded.id,), ROOT)
        _bucket_add(self._by_declaration_id, declared_ids(seeded), ROOT)

    def _check(self) -> None:
        if self._done:
            raise RuntimeError("TreeBuilder already finished; it is single-use")

    def add_child(self, parent_key: NodeId, record: NodeRecord) -> NodeId:
        """Attach `record` under `parent_key` in place; return the new child key."""
        self._check()
        parent = self._nodes[parent_key]
        if parent.is_external:
            raise ValueError(f"cannot add a child to external node {parent_key}")
        child_rec = replace(
            record, children=() if record.children is not None else None
        )
        siblings = parent.children or ()
        child_key = (*parent_key, _segment_for(siblings, child_rec))
        self._nodes[child_key] = child_rec
        self._nodes[parent_key] = replace(parent, children=(*siblings, child_key))
        _bucket_add(self._by_local_id, (child_rec.id,), child_key)
        _bucket_add(self._by_declaration_id, declared_ids(child_rec), child_key)
        return child_key

    def finish(self) -> NodeTree:
        """Freeze the staged nodes into a `NodeTree` and spend this builder."""
        self._check()
        self._done = True
        return NodeTree(
            root=ROOT,
            nodes=PersistentMap(self._nodes, _own=True),
            by_local_id=PersistentMap(self._by_local_id, _own=True),
            by_declaration_id=PersistentMap(self._by_declaration_id, _own=True),
            mode=self._mode,
            manifests=self._manifests,
        )
