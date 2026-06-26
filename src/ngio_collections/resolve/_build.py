"""The pure, synchronous tree builder: parsed documents → a `NodeTree`.

`build` walks an entry document's payload and produces a `NodeTree`, with no IO
of its own — every document it might need is supplied up front in `docs` (the
`fetch_all` shell gathers them). Two modes:

- `inline=False` (open): each cross-document stub becomes a *reference* record;
  the tree spans one document and stays editable.
- `inline=True` (open_inlined): each resolvable stub is spliced into the tree in
  place — the target's root replaces the stub, the stub's attributes overlay the
  target (stub wins), the name falls back to the stub, and the target keeps its
  own children, type, and pristine id. The result is a `resolved` collection.

Resolution degrades gracefully and deterministically: a stub is left unresolved
(a reference record) when the hop budget is exhausted (`depth`), a cycle is hit,
the target was not fetched, or its root type does not match the stub. `on_error`
chooses between leaving the stub (`"skip"`) and raising (`"raise"`). Identity is
the structural `NodeId` path, so the same document inlined twice yields distinct
nodes with no id rewriting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from pydantic import JsonValue

from ngio_collections.graph import ROOT, NodeId, NodeRecord, NodeTree, Reference, TreeBuilder
from ngio_collections.models._paths import DocPath, meta_url
from ngio_collections.resolve._document import Document

OnError = Literal["skip", "raise"]

Docs = Mapping[str, Document]


def build(
    entry_url: str,
    docs: Docs,
    *,
    inline: bool,
    depth: int | None = None,
    on_error: OnError = "skip",
) -> NodeTree:
    """Build a `NodeTree` from the document at `entry_url` using `docs`.

    Args:
        entry_url: The entry document's location (normalised internally).
        docs: A mapping of normalised document URL → parsed `Document`; must
            contain at least `entry_url`.
        inline: Whether to splice resolvable cross-document stubs in place.
        depth: Max boundary hops to follow when inlining (`None` unlimited,
            `0` = entry document only).
        on_error: `"skip"` leaves unresolvable stubs as reference records;
            `"raise"` propagates the failure.

    Returns:
        A `NodeTree` (`editable` when `inline=False`, else `resolved`).

    Raises:
        KeyError: If `entry_url` is not present in `docs`.
    """
    entry_url = meta_url(entry_url)
    doc = docs[entry_url]
    mode = "resolved" if inline else "editable"
    tree = TreeBuilder(_materialized_record(doc.root, doc.url), mode=mode)
    builder = _Builder(docs, inline, on_error)
    builder.add_children(tree, ROOT, doc.root, doc, depth, frozenset({entry_url}))
    return tree.finish()


@dataclass(frozen=True, slots=True)
class _Resolved:
    """How one payload dict materialises: the record plus how to recurse into it.

    `children_source` is the node dict whose `nodes` should be recursed (the dict
    itself for a materialized node, the target root for an inlined stub), or
    `None` to stop (a leaf, or a stub left unresolved). `doc`, `depth`, and
    `ancestors` are the context that recursion continues under.
    """

    record: NodeRecord
    children_source: dict | None
    doc: Document
    depth: int | None
    ancestors: frozenset[str]


class _Builder:
    """Carries the immutable build context while recursing the payload tree."""

    def __init__(self, docs: Docs, inline: bool, on_error: OnError) -> None:
        """Bind the document set and the inline / error policy for this build."""
        self.docs = docs
        self.inline = inline
        self.on_error = on_error

    def add_children(
        self,
        tree: TreeBuilder,
        parent_key: NodeId,
        source: dict,
        doc: Document,
        depth: int | None,
        ancestors: frozenset[str],
    ) -> None:
        """Add every child in `source["nodes"]` under `parent_key`, recursively."""
        for child_dict in source.get("nodes") or ():
            self._add_node(tree, parent_key, child_dict, doc, depth, ancestors)

    def _add_node(
        self,
        tree: TreeBuilder,
        parent_key: NodeId,
        node_dict: dict,
        doc: Document,
        depth: int | None,
        ancestors: frozenset[str],
    ) -> None:
        """Resolve `node_dict`, attach it under `parent_key`, and recurse."""
        resolved = self._resolve(node_dict, doc, depth, ancestors)
        key = tree.add_child(parent_key, resolved.record)
        if resolved.children_source is not None:
            self.add_children(
                tree,
                key,
                resolved.children_source,
                resolved.doc,
                resolved.depth,
                resolved.ancestors,
            )

    def _resolve(
        self,
        node_dict: dict,
        doc: Document,
        depth: int | None,
        ancestors: frozenset[str],
    ) -> _Resolved:
        """Decide whether `node_dict` is materialized, a reference, or inlined."""
        if node_dict.get("path") is None:
            record = _materialized_record(node_dict, doc.url)
            return _Resolved(record, node_dict, doc, depth, ancestors)
        if not self.inline:
            return _Resolved(_reference_record(node_dict, doc.url), None, doc, depth, ancestors)
        return self._inline_stub(node_dict, doc, depth, ancestors)

    def _inline_stub(
        self,
        node_dict: dict,
        doc: Document,
        depth: int | None,
        ancestors: frozenset[str],
    ) -> _Resolved:
        """Try to splice the stub `node_dict`'s target in; else leave a reference."""
        stub = _reference_record(node_dict, doc.url)
        leave = _Resolved(stub, None, doc, depth, ancestors)
        if depth == 0:
            return leave  # hop budget exhausted
        try:
            target_url = meta_url(DocPath.model_validate(node_dict["path"]).resolve(doc.url))
        except Exception:
            if self.on_error == "raise":
                raise
            return leave
        if target_url in ancestors:
            return leave  # cycle
        target = self.docs.get(target_url)
        if target is None:
            if self.on_error == "raise":
                raise FileNotFoundError(
                    f"reference target {target_url!r} was not fetched"
                )
            return leave
        if node_dict.get("type") != target.root.get("type"):
            if self.on_error == "raise":
                raise TypeError(
                    f"stub type {node_dict.get('type')!r} does not match target "
                    f"root type {target.root.get('type')!r} at {target_url!r}"
                )
            return leave
        merged = _merge_record(node_dict, target.root, target.url)
        next_depth = None if depth is None else depth - 1
        return _Resolved(merged, target.root, target, next_depth, ancestors | {target_url})


def _attributes(node_dict: dict) -> Mapping[str, JsonValue]:
    """Return a node dict's attributes, defaulting to an empty mapping."""
    return node_dict.get("attributes") or {}


def _materialized_record(node_dict: dict, origin_url: str) -> NodeRecord:
    """Build the record for an embedded node (branch when it has `nodes`)."""
    return NodeRecord(
        type=node_dict["type"],
        name=node_dict.get("name"),
        id=node_dict.get("id"),
        attributes=_attributes(node_dict),
        children=() if "nodes" in node_dict else None,
        origin_url=origin_url,
    )


def _reference_record(node_dict: dict, origin_url: str) -> NodeRecord:
    """Build a reference record (a left-in-place cross-document stub)."""
    path = DocPath.model_validate(node_dict["path"])
    return NodeRecord(
        type=node_dict["type"],
        name=node_dict.get("name"),
        id=node_dict.get("id"),
        attributes=_attributes(node_dict),
        ref=Reference(path=path, id=node_dict.get("id")),
        origin_url=origin_url,
    )


def _merge_record(stub_dict: dict, target_root: dict, target_url: str) -> NodeRecord:
    """Merge an inlined stub into its target root (stub attrs win, name falls back)."""
    target_attrs = _attributes(target_root)
    stub_attrs = _attributes(stub_dict)
    attributes = {**target_attrs, **stub_attrs} if stub_attrs else target_attrs
    name = target_root.get("name")
    if name is None:
        name = stub_dict.get("name")
    return NodeRecord(
        type=target_root["type"],
        name=name,
        id=target_root.get("id"),
        attributes=attributes,
        children=() if "nodes" in target_root else None,
        origin_url=target_url,
    )
